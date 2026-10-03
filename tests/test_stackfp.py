import os
import sqlite3
import tempfile
import unittest

import stackfp
from stackfp import Store, TraceParseError, fingerprint, ingest


def db_path():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    os.unlink(path)
    return path


# 抑制与因果多层交错，且父栈（Mid）本身也使用省略行
COMPACT_TRACE = (
    "RootException: root\n"
    "\tat app.Main.main(Main.java:10)\n"
    "\tat app.Runner.run(Runner.java:20)\n"
    "Caused by: MidException: mid\n"
    "\tat app.Worker.work(Worker.java:30)\n"
    "\t... 1 more\n"
    "\tSuppressed: SupA: a1\n"
    "\t\tat app.A.x(A.java:1)\n"
    "\t\t... 2 more\n"
    "\tSuppressed: SupB: b1\n"
    "\t\tat app.B.y(B.java:2)\n"
    "\t\t... 1 more\n"
    "Caused by: LeafException: leaf\n"
    "\tat app.Leaf.go(Leaf.java:40)\n"
    "\t... 2 more"
)

# 与上面完全等价的展开版本（行号刻意不同）
EXPANDED_TRACE = (
    "RootException: root\n"
    "\tat app.Main.main(Main.java:10)\n"
    "\tat app.Runner.run(Runner.java:20)\n"
    "Caused by: MidException: mid\n"
    "\tat app.Worker.work(Worker.java:30)\n"
    "\tat app.Runner.run(Runner.java:99)\n"
    "\tSuppressed: SupA: a1\n"
    "\t\tat app.A.x(A.java:1)\n"
    "\t\tat app.Worker.work(Worker.java:88)\n"
    "\t\tat app.Runner.run(Runner.java:77)\n"
    "\tSuppressed: SupB: b1\n"
    "\t\tat app.B.y(B.java:2)\n"
    "\t\tat app.Runner.run(Runner.java:66)\n"
    "Caused by: LeafException: leaf\n"
    "\tat app.Leaf.go(Leaf.java:40)\n"
    "\tat app.Worker.work(Worker.java:55)\n"
    "\tat app.Runner.run(Runner.java:44)"
)


class FingerprintTest(unittest.TestCase):
    def test_omitted_equivalent_to_expanded(self):
        self.assertEqual(
            fingerprint("m", COMPACT_TRACE), fingerprint("m", EXPANDED_TRACE)
        )

    def test_normalization_equivalent(self):
        messy = COMPACT_TRACE.replace("\n", "\r\n")
        messy = messy.replace("\tat app.Main.main(Main.java:10)",
                              "\tat app.Main.main(Main.java:10) \t")
        messy += "\n\n\n"
        self.assertEqual(fingerprint("m", COMPACT_TRACE), fingerprint("m", messy))

    def test_message_normalization(self):
        self.assertEqual(
            fingerprint("hello \r\nworld\n\n", "E: x"),
            fingerprint("hello\nworld", "E: x"),
        )

    def test_flattened_frames_same_but_tree_differs(self):
        t1 = "A: m\n\tat x.X.f(X.java:1)\n\tat y.Y.g(Y.java:2)"
        t2 = "A: m\n\tat x.X.f(X.java:1)\nCaused by: B: m\n\tat y.Y.g(Y.java:2)"
        self.assertNotEqual(fingerprint("m", t1), fingerprint("m", t2))

    def test_swapped_suppressed_children_differ(self):
        t1 = ("R: r\n"
              "\tSuppressed: SupA: a\n\t\tat p.A.f(A.java:1)\n"
              "\tSuppressed: SupB: b\n\t\tat p.B.g(B.java:2)")
        t2 = ("R: r\n"
              "\tSuppressed: SupB: b\n\t\tat p.B.g(B.java:2)\n"
              "\tSuppressed: SupA: a\n\t\tat p.A.f(A.java:1)")
        self.assertNotEqual(fingerprint("m", t1), fingerprint("m", t2))

    def test_message_digits_not_masked(self):
        t = "E: error code 123 at /tmp/x"
        self.assertNotEqual(fingerprint("m", t), fingerprint("m", t.replace("123", "124")))
        self.assertNotEqual(fingerprint("id 1", "E: x"), fingerprint("id 2", "E: x"))

    def test_field_boundaries_unambiguous(self):
        # 朴素拼接会得到相同字节流的两组输入，规范序列化必须区分
        self.assertNotEqual(fingerprint("ab", "E: c"), fingerprint("a", "E: bc"))
        t1 = "X: bc"
        t2 = "Xb: c"
        self.assertNotEqual(fingerprint("m", t1), fingerprint("m", t2))

    def test_location_kinds_not_conflated(self):
        base = "E: x\n\tat a.B.c(B.java:1)"
        native = "E: x\n\tat a.B.c(Native Method)"
        unknown = "E: x\n\tat a.B.c(Unknown Source)"
        fps = {fingerprint("m", base), fingerprint("m", native), fingerprint("m", unknown)}
        self.assertEqual(len(fps), 3)
        # 同类位置仅行号/文件名不同 -> 同指纹
        self.assertEqual(
            fingerprint("m", base), fingerprint("m", "E: x\n\tat a.B.c(Other.java:99)")
        )

    def test_frame_class_method_preserved(self):
        t1 = "E: x\n\tat a.B.c(B.java:1)"
        t2 = "E: x\n\tat a.B.d(B.java:1)"
        self.assertNotEqual(fingerprint("m", t1), fingerprint("m", t2))


class ParseRejectionTest(unittest.TestCase):
    def assert_rejected(self, trace):
        with self.assertRaises(TraceParseError):
            fingerprint("m", trace)

    def test_garbage_line(self):
        self.assert_rejected("E: x\n\tgarbage line")

    def test_space_indentation(self):
        self.assert_rejected("E: x\n    at a.B.c(B.java:1)")

    def test_root_omitted_forbidden(self):
        self.assert_rejected("E: x\n\tat a.B.c(B.java:1)\n\t... 1 more")

    def test_omitted_exceeds_parent_stack(self):
        self.assert_rejected("E: x\n\tat a.B.c(B.java:1)\nCaused by: F: y\n\t... 2 more")

    def test_frame_after_suppressed(self):
        self.assert_rejected(
            "R: r\n\tSuppressed: S: s\n\tat a.B.c(B.java:1)"
        )

    def test_chained_causes_ok(self):
        # R <- A <- B 是合法的两层因果链
        fingerprint("m", "R: r\nCaused by: A: a\nCaused by: B: b")

    def test_duplicate_omitted_line(self):
        self.assert_rejected(
            "R: r\n\tat a.B.c(B.java:1)\nCaused by: F: y\n\t... 1 more\n\t... 1 more"
        )

    def test_bad_frame_location(self):
        self.assert_rejected("E: x\n\tat a.B.c(B.java:abc)")

    def test_empty_trace(self):
        self.assert_rejected("")

    def test_header_type_with_space(self):
        self.assert_rejected("Bad Type: x")


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.path = db_path()

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_dedup_same_project_and_reopen(self):
        with Store(self.path) as store:
            r1 = store.ingest("proj", "m", COMPACT_TRACE)
            r2 = store.ingest("proj", "m", EXPANDED_TRACE)
        self.assertEqual(r1[0], r1[1])
        self.assertEqual(r2[1], r1[1])
        # 重开库后仍归并到最早记录
        with Store(self.path) as store:
            r3 = store.ingest("proj", "m", COMPACT_TRACE)
        self.assertEqual(r3[1], r1[1])
        self.assertNotEqual(r3[0], r1[0])

    def test_cross_project_not_merged(self):
        with Store(self.path) as store:
            r1 = store.ingest("p1", "m", COMPACT_TRACE)
            r2 = store.ingest("p2", "m", COMPACT_TRACE)
        self.assertNotEqual(r1[1], r2[1])
        self.assertEqual(r2[0], r2[1])

    def test_module_level_ingest(self):
        r1 = ingest("proj", "m", COMPACT_TRACE, db_path=self.path)
        r2 = ingest("proj", "m", EXPANDED_TRACE, db_path=self.path)
        self.assertEqual(r1[1], r2[1])

    def test_rejected_trace_creates_no_record(self):
        bad = "E: x\n\tat a.B.c(B.java:1)\nCaused by: F: y\n\t... 5 more"
        with Store(self.path) as store:
            with self.assertRaises(TraceParseError):
                store.ingest("proj", "m", bad)
        conn = sqlite3.connect(self.path)
        count = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_long_cause_chain_within_50kib(self):
        lines = ["E0: m0"]
        for i in range(1, 1200):
            lines.append("Caused by: E%d: m" % i)
            lines.append("\tat c.C.m(C.java:1)")
        trace = "\n".join(lines)
        self.assertLessEqual(len(trace.encode("utf-8")), 50 * 1024)
        with Store(self.path) as store:
            r1 = store.ingest("proj", "m", trace)
            r2 = store.ingest("proj", "m", trace)
        self.assertEqual(r1[1], r2[1])


if __name__ == "__main__":
    unittest.main()
