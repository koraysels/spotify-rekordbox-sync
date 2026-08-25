from rbsync.normalize import (
    normalize_title,
    normalize_artist,
    split_artists,
    extract_mix_tags,
)


class TestNormalizeTitle:
    def test_lowercases_and_collapses_whitespace(self):
        assert normalize_title("  Panda   SONG ") == "panda song"

    def test_strips_diacritics(self):
        assert normalize_title("Café Del Már") == "cafe del mar"

    def test_strips_original_version_noise(self):
        assert normalize_title("Bake Sale (Original Version)") == "bake sale"

    def test_strips_official_song_noise(self):
        assert normalize_title("Panda (OFFICIAL SONG)") == "panda"

    def test_strips_official_video_noise(self):
        assert normalize_title("Versace (Official Video)") == "versace"

    def test_strips_prod_by_brackets(self):
        assert (
            normalize_title("I Don't Sell Molly No More [Prod. By Sonny Digital]")
            == "i dont sell molly no more"
        )

    def test_strips_prod_by_parens(self):
        assert normalize_title("Touch Da Ground (pro by Yunggordon)") == "touch da ground"

    def test_strips_leading_track_number(self):
        assert normalize_title("03 Versace") == "versace"

    def test_keeps_number_that_is_part_of_title(self):
        assert normalize_title("7 Rings") == "7 rings"

    def test_strips_feat_suffix(self):
        assert normalize_title("Bruxelles arrive (feat. Caballero)") == "bruxelles arrive"

    def test_preserves_remix_descriptor(self):
        assert normalize_title("Strobe (Deadmau5 Remix)") == "strobe deadmau5 remix"

    def test_empty_input_is_safe(self):
        assert normalize_title("") == ""
        assert normalize_title(None) == ""


class TestSplitArtists:
    def test_splits_on_ampersand(self):
        assert split_artists("Kool John & P-Lo") == ["kool john", "p lo"]

    def test_splits_on_ft(self):
        assert split_artists("Wiz Khalifa Ft. Travis Scott") == ["wiz khalifa", "travis scott"]

    def test_splits_on_feat(self):
        assert split_artists("Skrillex feat. Sirah") == ["skrillex", "sirah"]

    def test_splits_on_comma(self):
        assert split_artists("Migos, Drake") == ["migos", "drake"]

    def test_splits_on_vs(self):
        assert split_artists("Prodigy vs Pendulum") == ["prodigy", "pendulum"]

    def test_does_not_split_x_inside_word(self):
        assert split_artists("Xavier Rudd") == ["xavier rudd"]

    def test_single_artist(self):
        assert split_artists("Migos") == ["migos"]

    def test_empty_is_empty_list(self):
        assert split_artists("") == []
        assert split_artists(None) == []


class TestNormalizeArtist:
    def test_strips_diacritics_and_lowercases(self):
        assert normalize_artist("Roméo Elvis") == "romeo elvis"

    def test_strips_the_prefix(self):
        assert normalize_artist("The Prodigy") == "prodigy"


class TestExtractMixTags:
    def test_detects_remix(self):
        assert "remix" in extract_mix_tags("Strobe (Deadmau5 Remix)")

    def test_detects_extended(self):
        assert "extended" in extract_mix_tags("Adagio For Strings (Extended Mix)")

    def test_detects_radio_edit(self):
        assert "radio" in extract_mix_tags("Titanium (Radio Edit)")

    def test_detects_live(self):
        assert "live" in extract_mix_tags("Song (Live at Wembley)")

    def test_plain_title_has_no_tags(self):
        assert extract_mix_tags("Versace") == set()

    def test_does_not_match_live_inside_word(self):
        assert extract_mix_tags("Deliver Me") == set()
