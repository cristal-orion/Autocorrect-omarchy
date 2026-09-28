// Linux laboratory adapter for the unmodified Apache-2.0 AOSP LatinIME core.
// No JVM: only the array operations and absent Android logging used by this
// pinned native call path are implemented. Not a general JNI implementation.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <codecvt>
#include <cstring>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <locale>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
#include <json-c/json.h>
#include "jni.h"
#include "dictionary/property/ngram_context.h"
#include "dictionary/property/ngram_property.h"
#include "dictionary/property/unigram_property.h"
#include "dictionary/structure/dictionary_structure_with_buffer_policy_factory.h"
#include "suggest/core/dictionary/dictionary.h"
#include "suggest/core/layout/proximity_info.h"
#include "suggest/core/result/suggestion_results.h"
#include "suggest/core/session/dic_traverse_session.h"
#include "suggest/core/suggest_options.h"
#include "utils/autocorrection_threshold_utils.h"

using namespace latinime;
using Clock = std::chrono::steady_clock;
using Json = std::unique_ptr<json_object, decltype(&json_object_put)>;

static double elapsed(Clock::time_point start) {
    return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}

static std::vector<int> decode(const std::string &text) {
    std::wstring_convert<std::codecvt_utf8<char32_t>, char32_t> converter;
    auto decoded = converter.from_bytes(text);
    std::vector<int> result(decoded.begin(), decoded.end());
    for (int cp : result) {
        if (cp == 0 || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff))
            throw std::runtime_error("Invalid Unicode scalar");
    }
    return result;
}

static std::string encode(const int *points, int length) {
    std::u32string value;
    for (int i = 0; i < length && points[i]; ++i) value.push_back(points[i]);
    return std::wstring_convert<std::codecvt_utf8<char32_t>, char32_t>().to_bytes(value);
}

namespace host_arrays {
struct View { void *data; size_t count; bool floating; };
static std::unordered_map<jarray, View> arrays;

template<class T, class Base> class Array : public Base {
 public:
    std::vector<T> values;
    explicit Array(std::vector<T> data) : values(std::move(data)) {
        arrays.emplace(this, View{values.data(), values.size(), std::is_same<T, float>::value});
    }
    explicit Array(size_t count) : Array(std::vector<T>(count)) {}
    ~Array() { arrays.erase(this); }
    Array(const Array &) = delete;
    Array &operator=(const Array &) = delete;
};
using Ints = Array<int, _jintArray>;
using Floats = Array<float, _jfloatArray>;

template<class T> static T *region(jarray array, jsize start, jsize length) {
    auto &view = arrays.at(array);
    if (start < 0 || length < 0 || size_t(start) + size_t(length) > view.count
            || view.floating != std::is_same<T, float>::value)
        throw std::runtime_error("Invalid host JNI array access");
    return static_cast<T *>(view.data) + start;
}

static JNINativeInterface functions = [] {
    JNINativeInterface table{};
    table.FindClass = [](JNIEnv *, const char *) -> jclass { return nullptr; };
    table.ExceptionClear = [](JNIEnv *) {};
    table.GetArrayLength = [](JNIEnv *, jarray a) -> jsize { return arrays.at(a).count; };
    table.GetIntArrayRegion = [](JNIEnv *, jintArray a, jsize s, jsize n, jint *out) {
        std::copy_n(region<int>(a, s, n), n, out);
    };
    table.GetFloatArrayRegion = [](JNIEnv *, jfloatArray a, jsize s, jsize n, jfloat *out) {
        std::copy_n(region<float>(a, s, n), n, out);
    };
    table.SetIntArrayRegion = [](JNIEnv *, jintArray a, jsize s, jsize n, const jint *in) {
        std::copy_n(in, n, region<int>(a, s, n));
    };
    table.SetFloatArrayRegion = [](JNIEnv *, jfloatArray a, jsize s, jsize n, const jfloat *in) {
        std::copy_n(in, n, region<float>(a, s, n));
    };
    return table;
}();
static JNIEnv env{&functions};
}

struct Keyboard {
    std::unordered_map<int, std::pair<int, int>> centers;
    std::unique_ptr<ProximityInfo> proximity;
    Keyboard() {
        std::vector<int> codes, xs, ys, widths, heights;
        const std::vector<std::string> rows = {"1234567890'ì", "qwertyuiopè+", "asdfghjklòàù", "<zxcvbnm,.-"};
        for (int r = 0; r < int(rows.size()); ++r) {
            auto row = decode(rows[r]);
            for (int c = 0; c < int(row.size()); ++c) {
                codes.push_back(row[c]); xs.push_back(c * 100 + r * 25); ys.push_back(r * 100);
                widths.push_back(100); heights.push_back(100);
            }
        }
        codes.push_back(' '); xs.push_back(300); ys.push_back(400);
        widths.push_back(500); heights.push_back(100);
        std::vector<float> sx, sy, radii;
        for (size_t i = 0; i < codes.size(); ++i) {
            centers[codes[i]] = {xs[i] + widths[i] / 2, ys[i] + 50};
            sx.push_back(centers[codes[i]].first); sy.push_back(centers[codes[i]].second);
            radii.push_back(50.0f);
        }
        // 50-unit grid cells. Neighbours are ordered by distance, within 1.5 keys.
        std::vector<int> grid(24 * 10 * MAX_PROXIMITY_CHARS_SIZE, NOT_A_CODE_POINT);
        for (int gy = 0; gy < 10; ++gy) for (int gx = 0; gx < 24; ++gx) {
            std::vector<std::pair<int, int>> near;
            for (int cp : codes) {
                auto [cx, cy] = centers.at(cp);
                int dx = cx - (gx * 50 + 25), dy = cy - (gy * 50 + 25);
                if (dx * dx + dy * dy <= 150 * 150) near.emplace_back(dx * dx + dy * dy, cp);
            }
            std::sort(near.begin(), near.end());
            for (size_t i = 0; i < near.size() && i < MAX_PROXIMITY_CHARS_SIZE; ++i)
                grid[(gy * 24 + gx) * MAX_PROXIMITY_CHARS_SIZE + i] = near[i].second;
        }
        using namespace host_arrays;
        Ints g(grid), x(xs), y(ys), w(widths), h(heights), c(codes);
        Floats fx(sx), fy(sy), fr(radii);
        proximity = std::make_unique<ProximityInfo>(&env, 1200, 500, 24, 10, 100, 100,
                &g, codes.size(), &x, &y, &w, &h, &c, &fx, &fy, &fr);
    }
};

static std::unique_ptr<Dictionary> openDictionary(const std::string &path, bool writable = false) {
    auto policy = DictionaryStructureWithBufferPolicyFactory::newPolicyForExistingDictFile(
            path.c_str(), 0, 0, writable);
    if (!policy) throw std::runtime_error("Cannot open native dictionary directory");
    return std::make_unique<Dictionary>(&host_arrays::env, std::move(policy));
}

static int dictionaryCount(Dictionary &dict, const char *key) {
    char result[32]{};
    dict.getProperty(key, std::strlen(key), result, sizeof(result));
    return std::stoi(result);
}

static void compileDictionary(const std::string &path, const std::string &destination) {
    if (std::filesystem::exists(destination) || std::filesystem::exists(destination + ".tmp"))
        throw std::runtime_error("Dictionary destination must be new");
    int words = 0, bigrams = 0;
    DictionaryHeaderStructurePolicy::AttributeMap attributes;
    auto policy = DictionaryStructureWithBufferPolicyFactory::newPolicyForOnMemoryDict(
            403, std::vector<int>{'i', 't'}, &attributes);
    if (!policy) throw std::runtime_error("Cannot create native dictionary");
    auto dict = std::make_unique<Dictionary>(&host_arrays::env, std::move(policy));
    std::ifstream input(path);
    if (!input) throw std::runtime_error("Cannot read dictionary TSV");
    std::string line;
    bool ngramsStarted = false;
    while (std::getline(input, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::vector<std::string> fields;
        size_t pos = 0, end;
        while ((end = line.find('\t', pos)) != std::string::npos) {
            fields.push_back(line.substr(pos, end - pos)); pos = end + 1;
        }
        fields.push_back(line.substr(pos));
        if (fields.size() != 3 && fields.size() != 4) throw std::runtime_error("Bad TSV row");
        size_t consumed;
        int score = std::stoi(fields[1], &consumed);
        if (consumed != fields[1].size() || score < 0 || score > 255) throw std::runtime_error("Bad score");
        auto target = decode(fields.back());
        if (target.empty() || target.size() >= MAX_WORD_LENGTH) throw std::runtime_error("Bad target length");
        bool ok = false;
        if (fields[0] == "1" && fields.size() == 3 && !ngramsStarted) {
            if (dict->getProbability(CodePointArrayView(target)) != NOT_A_PROBABILITY)
                throw std::runtime_error("Duplicate unigram");
            UnigramProperty prop(false, false, false, score, HistoricalInfo());
            ok = dict->addUnigramEntry(CodePointArrayView(target), &prop);
            ++words;
        } else if (fields[0] == "2" && fields.size() == 4) {
            ngramsStarted = true;
            auto prev = decode(fields[2]);
            if (prev.empty() || prev.size() >= MAX_WORD_LENGTH) throw std::runtime_error("Bad context length");
            if (dict->getProbability(CodePointArrayView(prev)) == NOT_A_PROBABILITY
                    || dict->getProbability(CodePointArrayView(target)) == NOT_A_PROBABILITY)
                throw std::runtime_error("Missing bigram endpoint");
            NgramContext ctx(prev.data(), prev.size(), false);
            NgramProperty prop(ctx, std::move(target), score, HistoricalInfo());
            ok = dict->addNgramEntry(&prop);
            ++bigrams;
        } else throw std::runtime_error("Bad order or TSV arity");
        if (!ok) throw std::runtime_error("Native dictionary insertion failed");
        if (dict->needsToRunGC(false)) {
            if (!dict->flushWithGC(destination.c_str())) throw std::runtime_error("Dictionary GC failed");
            dict = openDictionary(destination, true);
        }
    }
    if (!words) throw std::runtime_error("Empty dictionary");
    if (!dict->flushWithGC(destination.c_str())) throw std::runtime_error("Dictionary flush failed");
    dict = openDictionary(destination);
    if (dictionaryCount(*dict, "UNIGRAM_COUNT") != words || dictionaryCount(*dict, "BIGRAM_COUNT") != bigrams)
        throw std::runtime_error("Dictionary lost entries during compilation");
    std::cout << "{\"words\":" << words << ",\"bigrams\":" << bigrams << "}" << std::endl;
}

static json_object *field(json_object *obj, const char *name, json_type type) {
    json_object *value = nullptr;
    if (!json_object_object_get_ex(obj, name, &value) || !json_object_is_type(value, type))
        throw std::runtime_error(std::string("Invalid field: ") + name);
    return value;
}

static std::string stringValue(json_object *obj) {
    return std::string(json_object_get_string(obj), json_object_get_string_len(obj));
}

static Json query(Dictionary &dict, Keyboard &keyboard, json_object *request) {
    auto typed = stringValue(field(request, "input", json_type_string));
    auto input = decode(typed);
    if (input.size() >= MAX_WORD_LENGTH) throw std::runtime_error("Input must have fewer than 48 code points");
    auto previous = field(request, "previous", json_type_array);
    size_t count = json_object_array_length(previous);
    if (count > MAX_PREV_WORD_COUNT_FOR_N_GRAM) throw std::runtime_error("At most three previous words");
    int prev[MAX_PREV_WORD_COUNT_FOR_N_GRAM][MAX_WORD_LENGTH]{};
    int lengths[MAX_PREV_WORD_COUNT_FOR_N_GRAM]{};
    bool bos[MAX_PREV_WORD_COUNT_FOR_N_GRAM]{};
    for (size_t i = 0; i < count; ++i) {
        auto value = json_object_array_get_idx(previous, count - i - 1);
        if (!json_object_is_type(value, json_type_string)) throw std::runtime_error("Context must contain strings");
        auto cps = decode(stringValue(value));
        if (cps.empty() || cps.size() >= MAX_WORD_LENGTH) throw std::runtime_error("Bad context word length");
        std::copy(cps.begin(), cps.end(), prev[i]); lengths[i] = cps.size();
    }
    NgramContext context(prev, lengths, bos, count);
    std::vector<int> xs(input.size(), NOT_A_COORDINATE), ys(xs), times(input.size()), ids(input.size());
    for (size_t i = 0; i < input.size(); ++i) {
        auto key = keyboard.centers.find(input[i]);
        if (key != keyboard.centers.end()) { xs[i] = key->second.first; ys[i] = key->second.second; }
        times[i] = i * 100;
    }
    // A fresh traversal avoids incremental-prefix cache effects between requests.
    const auto start = Clock::now();
    DicTraverseSession session(&host_arrays::env, nullptr, true);
    int options[] = {0, 1, 1, 0, 1000};
    SuggestOptions settings(options, 5);
    SuggestionResults results(MAX_RESULTS);
    if (input.empty()) dict.getPredictions(&context, &results);
    else dict.getSuggestions(keyboard.proximity.get(), &session, xs.data(), ys.data(), times.data(),
            ids.data(), input.data(), input.size(), &context, &settings,
            NOT_A_WEIGHT_OF_LANG_MODEL_VS_SPATIAL_MODEL, &results);
    using namespace host_arrays;
    Ints n(1), points(MAX_RESULTS * MAX_WORD_LENGTH), scores(MAX_RESULTS), spaces(MAX_RESULTS),
            types(MAX_RESULTS), confidence(1);
    Floats weight(1);
    results.outputSuggestions(&env, &n, &points, &scores, &spaces, &types, &confidence, &weight);
    const double nativeMs = elapsed(start);
    Json response(json_object_new_object(), json_object_put);
    auto candidates = json_object_new_array();
    // Native output is worst-first; reversing preserves upstream tie order.
    for (int i = n.values[0] - 1; i >= 0; --i) {
        auto word = encode(points.values.data() + i * MAX_WORD_LENGTH, MAX_WORD_LENGTH);
        auto cps = decode(word);
        auto candidate = json_object_new_object();
        json_object_object_add(candidate, "term", json_object_new_string(word.c_str()));
        json_object_object_add(candidate, "score", json_object_new_int(scores.values[i]));
        json_object_object_add(candidate, "type", json_object_new_int64(uint32_t(types.values[i])));
        json_object_object_add(candidate, "normalized_score", input.empty() ? nullptr : json_object_new_double(
                AutocorrectionThresholdUtils::calcNormalizedScore(input.data(), input.size(),
                        cps.data(), cps.size(), scores.values[i])));
        json_object_object_add(candidate, "appropriate_for_autocorrection", json_object_new_boolean(
                (types.values[i] & Dictionary::KIND_FLAG_APPROPRIATE_FOR_AUTOCORRECTION) != 0));
        json_object_array_add(candidates, candidate);
    }
    json_object_object_add(response.get(), "input", json_object_new_string(typed.c_str()));
    json_object_object_add(response.get(), "candidates", candidates);
    json_object_object_add(response.get(), "native_ms", json_object_new_double(nativeMs));
    json_object_object_add(response.get(), "input_probability_code", json_object_new_int(
            input.empty() ? NOT_A_PROBABILITY : dict.getProbability(CodePointArrayView(input))));
    json_object_object_add(response.get(), "language_spatial_weight", json_object_new_double(weight.values[0]));
    return response;
}

int main(int argc, char **argv) {
    if (argc != 2 && !(argc == 4 && std::string(argv[1]) == "--compile")) {
        std::cerr << "Usage: latinime-probe DICTIONARY_DIRECTORY < requests.jsonl\n"
                  << "       latinime-probe --compile INPUT.tsv NEW_DIRECTORY\n";
        return 2;
    }
    try {
        if (argc == 4) { compileDictionary(argv[2], argv[3]); return 0; }
        auto start = Clock::now();
        auto dict = openDictionary(argv[1]);
        int words = dictionaryCount(*dict, "UNIGRAM_COUNT"), bigrams = dictionaryCount(*dict, "BIGRAM_COUNT");
        Keyboard keyboard;
        Json ready(json_object_new_object(), json_object_put);
        json_object_object_add(ready.get(), "ready", json_object_new_boolean(true));
        json_object_object_add(ready.get(), "words", json_object_new_int(words));
        json_object_object_add(ready.get(), "bigrams", json_object_new_int(bigrams));
        json_object_object_add(ready.get(), "startup_ms", json_object_new_double(elapsed(start)));
        std::cout << json_object_to_json_string_ext(ready.get(), JSON_C_TO_STRING_PLAIN) << std::endl;
        std::string line;
        while (std::getline(std::cin, line)) {
            Json response(nullptr, json_object_put);
            try {
                if (line.size() > 16384) throw std::runtime_error("Request too long");
                auto tokener = json_tokener_new();
                json_tokener_set_flags(tokener, JSON_TOKENER_STRICT | JSON_TOKENER_VALIDATE_UTF8);
                Json request(json_tokener_parse_ex(tokener, line.c_str(), line.size() + 1), json_object_put);
                bool valid = json_tokener_get_error(tokener) == json_tokener_success;
                json_tokener_free(tokener);
                if (!valid || !request || !json_object_is_type(request.get(), json_type_object))
                    throw std::runtime_error("Invalid JSON object");
                response = query(*dict, keyboard, request.get());
            } catch (const std::exception &error) {
                response.reset(json_object_new_object());
                json_object_object_add(response.get(), "error", json_object_new_string(error.what()));
            }
            std::cout << json_object_to_json_string_ext(response.get(), JSON_C_TO_STRING_PLAIN) << std::endl;
        }
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n'; return 1;
    }
    return 0;
}
