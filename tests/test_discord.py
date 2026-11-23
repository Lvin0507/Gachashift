"""The Discord report as coloured cards."""

import unittest
from unittest import mock

from gachashift import report as R


def game(gid, *statuses, notes=()):
    rep = R.GameReport(gid)
    for i, status in enumerate(statuses):
        rep.add(f"task{i}", status)
    for key in notes:
        rep.note(key)
    return rep


class ColourTest(unittest.TestCase):
    def test_all_fine(self):
        self.assertEqual(R.card_colour([game("zzz", R.OK), game("arknights", R.OK, R.ALREADY)]), R.CARD_OK)

    def test_something_to_look_at(self):
        self.assertEqual(R.card_colour([game("zzz", R.OK), game("genshin", R.OK, R.FAIL)]), R.CARD_WARN)

    def test_nothing_done(self):
        self.assertEqual(R.card_colour([game("zzz", R.OK), game("arknights", notes=["note.no_records"])]),
                         R.CARD_FAIL)

    def test_system_note(self):
        self.assertEqual(R.card_colour([game("system", notes=["note.locked"])]), R.CARD_WARN)


class CardsTest(unittest.TestCase):
    def test_one_card(self):
        cards = R.discord_cards([game("zzz", R.OK)], "en")
        self.assertEqual(len(cards), 1)
        self.assertTrue(cards[0]["title"].startswith("🌅 Gachashift report"))
        self.assertIn("Nothing needs you today", cards[0]["description"])
        self.assertEqual(cards[0]["color"], R.CARD_OK)

    def test_long_report_splits_between_lines(self):
        long_games = [game("endfield", *([R.FAIL] * 120))]
        cards = R.discord_cards(long_games, "en", limit=500)
        self.assertGreater(len(cards), 1)
        self.assertTrue(all(len(c["description"]) <= 500 for c in cards))
        self.assertNotIn("title", cards[1])
        joined = "\n".join(c["description"] for c in cards)
        self.assertEqual(joined, R.render_all(long_games, "en", compact=True))

    def test_sent_as_embeds(self):
        with mock.patch.object(R.requests, "post") as post:
            post.return_value.ok = True
            self.assertTrue(R.send_discord("https://discord.example/hook", [game("zzz", R.OK)], "zh"))
        payload = post.call_args.kwargs["json"]
        self.assertEqual(list(payload), ["embeds"])
        self.assertEqual(payload["embeds"][0]["color"], R.CARD_OK)


if __name__ == "__main__":
    unittest.main()
