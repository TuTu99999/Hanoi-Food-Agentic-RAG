import unittest
from unittest.mock import Mock

from embedding.warm_model_cache import warm_model_cache


class ModelCacheTests(unittest.TestCase):
    def test_cache_hit_does_not_download(self):
        loader = Mock()

        downloaded = warm_model_cache("test-model", loader=loader)

        self.assertFalse(downloaded)
        loader.assert_called_once_with(
            "test-model",
            device="cpu",
            local_files_only=True,
        )

    def test_cache_miss_downloads_once(self):
        loader = Mock(side_effect=[OSError("not cached"), object()])

        downloaded = warm_model_cache("test-model", loader=loader)

        self.assertTrue(downloaded)
        self.assertEqual(loader.call_count, 2)
        loader.assert_called_with(
            "test-model",
            device="cpu",
            local_files_only=False,
        )


if __name__ == "__main__":
    unittest.main()
