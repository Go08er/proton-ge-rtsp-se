#!/usr/bin/env python3
"""Evaluate the review source's actual pre-probe duration predicate, without Wine."""
import ast
import os
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get("GE119_DEMUXER_REVIEW", str(
    ROOT / "patches/ge-proton11-9-se2-p20/0001-winedmo-retain-bounded-network-and-origin-contract.patch")))


def expression(text, values):
    """Only the small boolean C expression extracted below is interpreted."""
    for before, after in (
        ("demuxer->ctx->iformat->name", "format_name"),
        ("params->url", "url"),
        ("avio_size( demuxer->ctx->pb )", "resource_size"),
        ("get_context_duration( demuxer->ctx, FALSE )", "duration"),
        ("demuxer->ctx->pb->seekable", "seekable"),
        ("demuxer->ctx->pb", "has_io"),
        ("AVIO_SEEKABLE_NORMAL", "1")):
        text = text.replace(before, after)
    text = re.sub(r"!(?!=)", " not ", text.replace("&&", " and ").replace("||", " or "))
    tree = ast.parse(" ".join(text.split()), mode="eval")
    allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
               ast.BinOp, ast.BitAnd, ast.Compare, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
               ast.Eq, ast.NotEq, ast.Name, ast.Load, ast.Constant, ast.Call)
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise ValueError("unsupported source expression")
    return bool(eval(compile(tree, str(SOURCE), "eval"), {"__builtins__": {}}, values))


class ContentClassification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text()
        if SOURCE.suffix == ".patch":
            # Read the candidate's actual postimage fragments, not a duplicate
            # hand-written predicate or an ignored work/ source snapshot.
            fragment = cls.source.split(
                "diff --git a/dlls/winedmo/unix_demuxer.c b/dlls/winedmo/unix_demuxer.c\n", 1)[1]
            fragment = fragment.split("diff --git ", 1)[0]
            cls.source = "\n".join(line[1:] for line in fragment.splitlines()
                                   if line.startswith((" ", "+")) and not line.startswith("+++"))
        cls.progressive = re.search(r"\bprogressive\s*=\s*([^;]+);", cls.source).group(1)
        section = cls.source.split("/* Preserve GE's finite-resource test", 1)[1]
        cls.predicate = re.search(r"if \(([\s\S]*?)\)\s*demuxer->nonseekable = TRUE;", section).group(1)
        helper = re.search(r"static BOOL is_http_progressive_url\([^;]*?\n\{([\s\S]*?)\n\}", cls.source)
        cls.url_hints = re.findall(r'strstr\( url, "([^"]+)" \)', helper.group(1)) if helper else []

    def latched(self, url, format_name, *, has_io=True, seekable=1, resource_size=4096, duration=0):
        values = dict(url=url, format_name=format_name, has_io=has_io, seekable=seekable,
                      resource_size=resource_size, duration=duration,
                      detected_hls=format_name == "hls",
                      is_http_progressive_url=lambda candidate: any(h in candidate for h in self.url_hints),
                      av_match_name=lambda name, names: name in names.split(","),
                      strstr=lambda haystack, needle: needle in haystack)
        values["progressive"] = expression(self.progressive, values)
        return expression(self.predicate, values)

    def test_detected_hls_never_uses_progressive_duration_guard(self):
        for url in ("https://media.invalid/live.mp4", "https://media.invalid/live.m3u8?file=a.mp4",
                    "https://r1.googlevideo.com/videoplayback?id=live"):
            with self.subTest(url=url):
                self.assertFalse(self.latched(url, "hls", resource_size=-1))

    def test_finite_non_mp4_ignores_mp4_query_hint(self):
        self.assertFalse(self.latched("https://media.invalid/audio.flac?file=.mp4", "flac"))
        self.assertFalse(self.latched("https://r1.googlevideo.com/videoplayback?id=audio", "matroska,webm"))

    def test_finite_mp4_remains_seekable_from_track_duration(self):
        self.assertFalse(self.latched("https://media.invalid/movie.mp4", "mov,mp4,m4a,3gp,3g2,mj2",
                                     duration=1830000000))

    def test_live_mp4_cannot_trust_first_fragment_duration(self):
        self.assertTrue(self.latched("https://media.invalid/movie.mp4", "mov,mp4,m4a,3gp,3g2,mj2",
                                    resource_size=-1, duration=10000000))

    def test_extensionless_mp4_uses_the_same_resource_guard(self):
        self.assertTrue(self.latched("https://media.invalid/playback", "mov,mp4,m4a,3gp,3g2,mj2",
                                    resource_size=-1, duration=10000000))


if __name__ == "__main__":
    unittest.main(verbosity=2)
