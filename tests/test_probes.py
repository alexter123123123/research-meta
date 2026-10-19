from mcs.parse.probes import SYNTHETIC, build_probes, is_article_path

HTML = """
<a href="/2026/10/19/world/europe/some-story.html">a</a>
<a href="https://www.example.com/politics/this-is-a-long-slug-here">b</a>
<a href="/tag/politics/some-tag-with-many-hyphens-in-it">tag</a>
<a href="/author/jane-doe-the-reporter-person">author</a>
<a href="https://other.com/2026/10/foreign-story">other host</a>
<a href="/live/2026/10/19/live-blog">live</a>
<a href="/news/article-12345.ece">ece</a>
<a href="/sport">section</a>
"""


def test_is_article_path():
    assert is_article_path("/2026/10/19/world/story.html")
    assert is_article_path("/politics/this-is-a-long-slug-here")
    assert not is_article_path("/tag/a-b-c-d-e-f")
    assert not is_article_path("/sport")
    assert not is_article_path("/story.html")  # depth < 2


def test_build_probes_samples_same_host_articles():
    probes, synth = build_probes(HTML, "https://www.example.com/")
    assert not synth
    assert probes[:2] == ["/", "/news/"]
    arts = probes[2:]
    assert len(arts) == 3
    assert all(not a.startswith(("/tag", "/author", "/live")) for a in arts)
    # deterministic
    assert build_probes(HTML, "https://www.example.com/") == (probes, synth)


def test_build_probes_synthetic_fallback():
    probes, synth = build_probes("<html></html>", "https://x.com/")
    assert synth and probes[-1] == SYNTHETIC
