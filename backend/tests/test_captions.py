import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.captions import make_ass


class AnimatedCaptionTests(unittest.TestCase):
    def test_word_timed_karaoke_events_are_written(self):
        segments = [{
            "start": 0.0,
            "end": 2.0,
            "text": "Hello world",
            "words": [
                {"start": 0.1, "end": 0.6, "text": "Hello"},
                {"start": 0.7, "end": 1.2, "text": "world"},
            ],
        }]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "captions.ass"
            result = make_ass(segments, 0.0, 2.0, target, "bold")
            content = target.read_text(encoding="utf-8")
        self.assertTrue(result)
        self.assertIn("[Events]", content)
        self.assertIn("\\kf", content)
        self.assertIn("Hello world", content)
        self.assertIn("DejaVu Sans,56", content)

    def test_no_words_returns_false_without_invalid_dialogue(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "captions.ass"
            result = make_ass([{"start": 0, "end": 1, "text": "No timing", "words": []}], 0, 1, target)
            content = target.read_text(encoding="utf-8")
        self.assertFalse(result)
        self.assertNotIn("Dialogue:", content)

    def test_clip_window_trims_word_times(self):
        segments = [{
            "words": [
                {"start": 1.0, "end": 1.5, "text": "before"},
                {"start": 2.0, "end": 2.5, "text": "inside"},
                {"start": 3.0, "end": 3.5, "text": "after"},
            ]
        }]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "captions.ass"
            make_ass(segments, 2.2, 3.2, target)
            content = target.read_text(encoding="utf-8")
        self.assertIn("inside", content)
        self.assertIn("after", content)
        self.assertNotIn("before", content)


if __name__ == "__main__":
    unittest.main()
