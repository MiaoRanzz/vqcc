from pathlib import Path
import tempfile
import unittest

from kaggle_auth import load_kaggle_api_token


class KaggleAuthTests(unittest.TestCase):
    def test_missing_token_preserves_existing_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {}
            self.assertIsNone(load_kaggle_api_token(env, Path(directory) / 'missing'))
            self.assertEqual(env, {})

    def test_file_token_is_reloaded_without_mcp_config_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'access_token'
            for token in ('test-token-one', 'test-token-two'):
                path.write_text(token + '\n')
                env = {}
                result = load_kaggle_api_token(env, path)
                self.assertEqual(env['KAGGLE_API_TOKEN'], token)
                self.assertIsNone(result)
                self.assertEqual(env, {'KAGGLE_API_TOKEN': token})

    def test_inherited_token_takes_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'access_token'
            path.write_text('file-token')
            env = {'KAGGLE_API_TOKEN': 'inherited-token'}
            load_kaggle_api_token(env, path)
            self.assertEqual(env['KAGGLE_API_TOKEN'], 'inherited-token')
