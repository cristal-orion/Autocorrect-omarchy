import struct
import unittest

from autocorrect_core.swiftkey_inspect import inspect_model


def u32(value):
    return struct.pack("<I", value)


def chunk(tag, header, body):
    content = u32(len(header)) + header + tag + body + tag
    return tag + u32(len(content)) + content


def model(*, nodes=2, word_id=1, version=b"\x08\x07", vocab_length=3):
    # Invented byte layout; no personal vocabulary or source export in tests.
    vocab = u32(3) + b"xyz" + u32(2) + bytes([0, vocab_length])
    tree = u32(nodes) + struct.pack("<HIHIHHH", word_id, 8, 1, 2, 0, 0, 0) + b"\0\0"
    header = b"DynamicNgramTermModel"
    content = u32(len(header)) + header + b"flue"
    content += chunk(b"voca", version, vocab) + chunk(b"dmap", b"", tree) + b"flue"
    return b"flue" + u32(len(content)) + content


class SwiftKeyInspectorTest(unittest.TestCase):
    def test_validated_tree_counts_do_not_claim_text_decoding(self):
        report = inspect_model(model())
        self.assertEqual(report["parsed_nodes"], 2)
        self.assertEqual(report["nodes_by_depth"], {1: 1, 2: 1})
        self.assertEqual(report["root_identifiers"], 1)
        self.assertFalse(report["vocabulary_decoded"])
        self.assertFalse(report["ready_for_context_import"])

    def test_rejects_wrong_version_sizes_ids_and_counts(self):
        for data in (model(version=b"\x08\x08"), model(nodes=3), model(nodes=1),
                     model(word_id=9), model(vocab_length=2), model()[:-1], b"random"):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                inspect_model(data)


if __name__ == "__main__":
    unittest.main()
