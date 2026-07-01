"""Real tests for history_surfer.replay (selection spec + claude driving)."""
import os
import unittest


class SelectionTest(unittest.TestCase):
    def setUp(self):
        from history_surfer import replay
        self.replay = replay

    def sel(self, spec, count):
        return self.replay.parse_selection(spec, count)

    def test_single_and_range(self):
        idx, warn = self.sel("0,3-5", 10)
        self.assertEqual(idx, [0, 3, 4, 5])
        self.assertEqual(warn, [])

    def test_open_end(self):
        idx, warn = self.sel("5-", 8)
        self.assertEqual(idx, [5, 6, 7])
        self.assertEqual(warn, [])

    def test_open_start(self):
        idx, _ = self.sel("-2", 5)
        self.assertEqual(idx, [0, 1, 2])

    def test_order_preserved(self):
        idx, _ = self.sel("5-,0,3-4", 8)
        self.assertEqual(idx, [5, 6, 7, 0, 3, 4])

    def test_duplicates_kept(self):
        idx, _ = self.sel("2,2,2", 5)
        self.assertEqual(idx, [2, 2, 2])

    def test_brackets_and_spaces_ok(self):
        idx, _ = self.sel("[0, 3-4, 6-]", 8)
        self.assertEqual(idx, [0, 3, 4, 6, 7])

    def test_out_of_range_single_warns_and_skips(self):
        idx, warn = self.sel("99", 5)
        self.assertEqual(idx, [])
        self.assertEqual(len(warn), 1)

    def test_range_past_end_warns_and_starts_skip(self):
        idx, warn = self.sel("10-", 5)
        self.assertEqual(idx, [])
        self.assertEqual(len(warn), 1)

    def test_range_truncated_warns_but_keeps_valid(self):
        idx, warn = self.sel("3-100", 5)
        self.assertEqual(idx, [3, 4])
        self.assertEqual(len(warn), 1)

    def test_garbage_token_warns(self):
        idx, warn = self.sel("abc", 5)
        self.assertEqual(idx, [])
        self.assertEqual(len(warn), 1)


if __name__ == "__main__":
    unittest.main()
