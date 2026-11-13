"""Test configuration.

The identity gate lets a genesis in only from the GitHub account that `src/openmasonry/network.toml` names
(`founder_github_id`, the founding account's id). The founder of every test lodge is `hiram`, so the tests run
with his id in its place; the tests of the rule itself set other values, and one reads the file itself.
"""
import hashlib

from openmasonry import canon

canon.FOUNDER_GITHUB_ID = int(hashlib.sha256(b"hiram").hexdigest()[:8], 16) + 1     # tests.test_protocol.gid("hiram")
