"""stackfp 测试套件。"""

import os
import sqlite3
import tempfile
import unittest

from stackfp import Store, TraceParseError, fingerprint

# 多层交错：根 R(3帧) -> 抑制 S1(1帧+省略2) -> 因果 C1(1帧+省略2)；
# R -> 因果 K(1帧+省略2) -> 抑制 S2(1帧+省略3)。父栈本身也含省略。
TRACE_OMITTED = (
    "com.example.RootException: root fail\n"
    "\tat com.app.Main.run(Main.java:10)\n"
    "\tat com.app.Main.work(Main.java:20)\n"
    "\tat com.app.Main.main(Main.java:30)\n"
    "\tSuppressed: com.example.SuppressedOne: sup one\n"
    "\t\tat com.app.Helper.close(Helper.java:40)\n"
    "\t\t... 2 more\n"
    "\tCaused by: com.example.CauseOne\n"
    "\t\tat com.app.Deep.fail(Deep.java:50)\n"
    "\t\t... 2 more\n"
    "Caused by: com.example.RootCause: deep cause\n"
    "\tat com.app.Core.exec(Core.java:60)\n"
    "\t... 2 more\n"
    "\tSuppressed: com.example.SuppressedTwo\n"
    "\t\tat com.app.Core.cleanup(Core.java:70)\n"
    "\t\t... 3 more\n"
)

# 完全展开版本：行号/文件名不同，另带 CRLF、行尾空格与末尾空行。
TRACE_EXPANDED = (
    "com.example.RootException: root fail\r\n"
    "\tat com.app.Main.run(Main.java:1) \t\r\n"
    "\tat com.app.Main.work(Main.java:2)\r\n"
    "\tat com.app.Main.main(Main.java:3)\r\n"
    "\tSuppressed: com.example.SuppressedOne: sup one\r\n"
    "\t\tat com.app.Helper.close(Helper.java:4)\r\n"
    "\t\tat com.app.Main.work(Main.java:5)\r\n"
    "\t\tat com.app.Main.main(Main.java:6)\r\n"
    "\tCaused by: com.example.CauseOne\r\n"
    "\t\tat com.app.Deep.fail(Deep.java:7)\r\n"
    "\t\tat com.app.Main.work(Main.java:8)\r\n"
    "\t\tat com.app.Main.main(Main.java:9)\r\n"
    "Caused by: com.example.RootCause: deep cause\r\n"
    "\tat com.app.Core.exec(Core.java:10)\r\n"
    "\tat com.app.Main.work(Main.java:11)\r\n"
    "\tat com.app.Main.main(Main.java:12)\r\n"
    "\tSuppressed: com.example.SuppressedTwo\r\n"
    "\t\tat com.app.Core.cleanup(Core.java:13)\r\n"
    "\t\tat com.app.Core.exec(Core.java:14)\r\n"
    "\t\tat com.app.Main.work(Main.java:15)\r\n"
    "\t\tat com.app.Main.main(Main.java:16)\r\n"
    "\r\n"
    "\r\n"
)


class StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)

    def tearDown(self) -> None:
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def record_count(self) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        finally:
            conn.close()


class FingerprintTest(unittest.TestCase):
    def test_interleaved_omission_matches_expanded(self) -> None:
        self.assertEqual(
            fingerprint("root fail", TRACE_OMITTED),
            fingerprint("root fail", TRACE_EXPANDED),
        )

    def test_line_number_and_file_ignored(self) -> None:
        t1 = "E\n\tat a.B.m(Foo.java:1)"
        t2 = "E\n\tat a.B.m(Bar.java:999)"
        self.assertEqual(fingerprint("m", t1), fingerprint("m", t2))

    def test_position_categories_distinct(self) -> None:
        base = "E\n\tat a.B.m(Foo.java:1)"
        native = "E\n\tat a.B.m(Native Method)"
        unknown = "E\n\tat a.B.m(Unknown Source)"
        fps = {fingerprint("", t) for t in (base, native, unknown)}
        self.assertEqual(len(fps), 3)

    def test_tree_attachment_matters(self) -> None:
        # 扁平帧序列与消息完全相同，但第二帧归属不同节点。
        t1 = "A\n\tat x.M(F.java:1)\n\tSuppressed: B\n\t\tat x.M(F.java:1)"
        t2 = "A\n\tat x.M(F.java:1)\n\tat x.M(F.java:1)\n\tSuppressed: B"
        self.assertNotEqual(fingerprint("", t1), fingerprint("", t2))

    def test_swapped_suppressed_not_merged(self) -> None:
        t1 = (
            "A\n\tSuppressed: B\n\t\tat x.M(F.java:1)\n"
            "\tSuppressed: C\n\t\tat y.N(F.java:2)"
        )
        t2 = (
            "A\n\tSuppressed: C\n\t\tat y.N(F.java:2)\n"
            "\tSuppressed: B\n\t\tat x.M(F.java:1)"
        )
        self.assertNotEqual(fingerprint("", t1), fingerprint("", t2))

    def test_message_digits_not_noise(self) -> None:
        t = "E\n\tat a.B.m(Foo.java:1)"
        self.assertNotEqual(fingerprint("error 1", t), fingerprint("error 2", t))
        t1 = "E: code 100\n\tat a.B.m(Foo.java:1)"
        t2 = "E: code 200\n\tat a.B.m(Foo.java:1)"
        self.assertNotEqual(fingerprint("", t1), fingerprint("", t2))

    def test_field_boundary_unambiguous(self) -> None:
        # 朴素拼接会得到相同串 "abc"，规范序列化必须区分。
        t1 = "a: bc"
        t2 = "ab: c"
        self.assertNotEqual(fingerprint("", t1), fingerprint("", t2))
        t3 = "E\n\tat ab.C(F.java:1)"
        t4 = "E\n\tat a.bC(F.java:1)"
        self.assertNotEqual(fingerprint("", t3), fingerprint("", t4))

    def test_message_is_independent_component(self) -> None:
        t = "E\n\tat a.B.m(Foo.java:1)"
        self.assertNotEqual(fingerprint("hello", t), fingerprint("", t))

    def test_deep_causal_chain_1200(self) -> None:
        parts = ["RootE"]
        for i in range(1200):
            parts.append(f"Caused by: E{i}")
            parts.append(f"\tat a.B.m(F.java:{i})")
        trace = "\n".join(parts)
        self.assertLessEqual(len(trace.encode("utf-8")), 50 * 1024)
        fp = fingerprint("deep", trace)
        self.assertEqual(len(fp), 64)


class RejectTest(unittest.TestCase):
    def assert_rejected(self, trace: str) -> None:
        with self.assertRaises(TraceParseError):
            fingerprint("", trace)

    def test_omitted_overflow_rejected(self) -> None:
        self.assert_rejected("E\n\tat a.B.m(F.java:1)\nCaused by: C\n\t... 2 more")

    def test_root_omitted_rejected(self) -> None:
        self.assert_rejected("E\n\tat a.B.m(F.java:1)\n\t... 1 more")

    def test_empty_trace_rejected(self) -> None:
        self.assert_rejected("")
        self.assert_rejected("\n\n")

    def test_garbage_line_rejected(self) -> None:
        self.assert_rejected("E\nhello world")
        self.assert_rejected("E\n\tat broken frame")
        self.assert_rejected("E\n\t... x more")
        self.assert_rejected(" E\n\tat a.B.m(F.java:1)")

    def test_orphan_suppressed_rejected(self) -> None:
        self.assert_rejected("E\n\t\tSuppressed: S")

    def test_caused_by_chain_is_valid(self) -> None:
        from stackfp.parser import parse_trace

        root = parse_trace("E\nCaused by: A\nCaused by: B")
        self.assertEqual(root.caused_by.type, "A")
        self.assertEqual(root.caused_by.caused_by.type, "B")

    def test_frame_after_omitted_rejected(self) -> None:
        self.assert_rejected(
            "E\n\tat a.B.m(F.java:1)\nCaused by: C\n\t... 1 more\n\tat a.B.m(F.java:2)"
        )


class IngestTest(StoreTestCase):
    def test_dedup_same_project_and_reopen(self) -> None:
        store = Store(self.db_path)
        r1 = store.ingest("proj", "root fail", TRACE_OMITTED)
        r2 = store.ingest("proj", "root fail", TRACE_EXPANDED)
        self.assertEqual(r1.record_id, r1.canonical_id)
        self.assertEqual(r2.canonical_id, r1.canonical_id)
        store.close()
        # 重开库后仍识别重复项
        store = Store(self.db_path)
        r3 = store.ingest("proj", "root fail", TRACE_OMITTED)
        self.assertEqual(r3.canonical_id, r1.canonical_id)
        store.close()

    def test_cross_project_not_merged(self) -> None:
        with Store(self.db_path) as store:
            r1 = store.ingest("p1", "m", TRACE_OMITTED)
            r2 = store.ingest("p2", "m", TRACE_OMITTED)
        self.assertNotEqual(r1.canonical_id, r2.canonical_id)
        self.assertEqual(r2.canonical_id, r2.record_id)

    def test_earliest_record_wins(self) -> None:
        with Store(self.db_path) as store:
            r1 = store.ingest("p", "m", TRACE_OMITTED)
            r2 = store.ingest("p", "m", TRACE_EXPANDED)
            r3 = store.ingest("p", "m", TRACE_OMITTED)
        self.assertEqual(r2.canonical_id, r1.record_id)
        self.assertEqual(r3.canonical_id, r1.record_id)

    def test_rejected_trace_writes_nothing(self) -> None:
        with Store(self.db_path) as store:
            store.ingest("p", "m", TRACE_OMITTED)
            with self.assertRaises(TraceParseError):
                store.ingest("p", "m", "E\nCaused by: C\n\t... 5 more")
            with self.assertRaises(TraceParseError):
                store.ingest("p", "m", "not a valid trace\nblah")
        self.assertEqual(self.record_count(), 1)

    def test_deep_chain_ingest(self) -> None:
        parts = ["RootE"]
        for i in range(1200):
            parts.append(f"Caused by: E{i}")
            parts.append(f"\tat a.B.m(F.java:{i})")
        trace = "\n".join(parts)
        with Store(self.db_path) as store:
            r1 = store.ingest("p", "deep", trace)
            r2 = store.ingest("p", "deep", trace)
        self.assertEqual(r2.canonical_id, r1.canonical_id)

    def test_trace_size_limit(self) -> None:
        big = "E\n" + "\tat a.B.m(F.java:1)\n" * 3000
        self.assertGreater(len(big.encode("utf-8")), 50 * 1024)
        with Store(self.db_path) as store:
            with self.assertRaises(ValueError):
                store.ingest("p", "m", big)
        self.assertEqual(self.record_count(), 0)


if __name__ == "__main__":
    unittest.main()
