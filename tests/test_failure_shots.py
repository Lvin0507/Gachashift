"""Which screenshots are sent: one when a task fails (MaaEnd, read live), and the screen at the
end only when the game ended badly."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from gachashift import report as R
from gachashift import runner
from gachashift.games.endfield import FailureWatch


def line(entry=None, task_id=None, message="", level="debug", **extra):
    rec = {"level": level, "message": message, **extra}
    if entry:
        rec["entry"] = entry
    if task_id is not None:
        rec["task_id"] = task_id
    return json.dumps(rec) + "\n"


def start(entry, task_id):
    return line(entry, task_id, "Checking aspect ratio before task execution")


# The shape of a real morning (27 Nov): Environment Monitoring hits an error, gives up 25 s
# later and logs "Task failed" just as the next task starts
MORNING = (
    start("DeliveryJobsMain", 11)
    + start("EnvironmentMonitoringMain", 12)
    + line(message="target not found after camera scan", level="info", component="CameraScanAction")
    + line(message="FailureCollector subtask failed", level="error", task="CleansingJadeExecute")
    + line("EnvironmentMonitoringMain", 12,
           "Task failed but entry is not in feedback hint list, skip feedback hint")
    + start("TrialOfSwordmancyMain", 13)
)


class FailureWatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name, "go-service.log")
        self.log.write_text("", encoding="utf-8")
        self.snaps, self.removed = [], []
        self.screen = "screen"   # what is on screen now, for telling the pictures apart

        def snap(key):
            path = f"{key}@{self.screen}.jpg"
            self.snaps.append(path)
            return path
        self.watch = FailureWatch(str(self.log), snap, self.removed.append)

    def write(self, text):
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(text)

    def test_picture_from_the_moment_of_the_error(self):
        self.write(start("EnvironmentMonitoringMain", 12))
        self.watch.poll()
        self.screen = "stuck"
        self.write(line(message="FailureCollector subtask failed", level="error"))
        self.watch.poll()
        self.screen = "next task"
        self.write(line("EnvironmentMonitoringMain", 12, "Task failed but entry is not in feedback hint list")
                   + start("TrialOfSwordmancyMain", 13))
        self.watch.poll()
        self.assertEqual(self.watch.close(), [("EnvironmentMonitoringMain", "EnvironmentMonitoringMain@stuck.jpg")])
        self.assertEqual(self.removed, [])

    def test_whole_morning_in_one_read(self):
        self.write(MORNING)
        self.assertEqual([k for k, _ in self.watch.close()], ["EnvironmentMonitoringMain"])
        self.assertEqual(len(self.snaps), 1)

    def test_task_that_recovers_keeps_no_picture(self):
        self.write(start("DijiangRewards", 2) + line(message="ocr miss", level="error"))
        self.watch.poll()
        self.write(start("OutpostTradingSchedule", 3))
        self.watch.poll()
        self.assertEqual(self.watch.close(), [])
        self.assertEqual(self.removed, self.snaps)

    def test_failure_without_an_error_line(self):
        self.write(start("VisitFriendsMain", 15) + line("VisitFriendsMain", 15, "Task failed"))
        self.assertEqual(self.watch.close(), [("VisitFriendsMain", "VisitFriendsMain@screen.jpg")])

    def test_half_written_line_waits(self):
        text = start("GiftOperatorMain", 18) + line("GiftOperatorMain", 18, "Task failed")
        self.write(text[:-20])
        self.watch.poll()
        self.assertEqual(self.snaps, [])
        self.write(text[-20:])
        self.watch.poll()
        self.assertEqual(len(self.watch.kept), 1)

    def test_one_picture_per_task(self):
        self.write(start("A", 1) + line(level="error") + line(level="error") + line("A", 1, "Task failed")
                   + line("A", 1, "Task failed"))
        self.assertEqual(len(self.watch.close()), 1)
        self.assertEqual(len(self.snaps), 1)

    def test_old_log_is_skipped(self):
        self.write(MORNING)
        watch = FailureWatch(str(self.log), lambda key: self.snaps.append(key) or key, self.removed.append,
                             offset=os.path.getsize(self.log))
        self.assertEqual(watch.close(), [])


def report(statuses, notes=()):
    rep = R.GameReport("endfield")
    for i, status in enumerate(statuses):
        rep.add(f"task{i}", status)
    for key in notes:
        rep.note(key)
    return rep


class EndShotTest(unittest.TestCase):
    def test_earlier_failure_with_later_tasks_done(self):
        self.assertFalse(runner.end_shot_wanted(report([R.OK, R.FAIL, R.OK, R.OK])))

    def test_last_task_failed(self):
        self.assertTrue(runner.end_shot_wanted(report([R.OK, R.OK, R.FAIL])))

    def test_last_task_failed_before_skipped_ones(self):
        self.assertTrue(runner.end_shot_wanted(report([R.OK, R.FAIL, R.SKIPPED])))

    def test_nothing_done(self):
        self.assertTrue(runner.end_shot_wanted(report([R.FAIL])))

    def test_run_ended_badly(self):
        for note in ("note.timeout", "note.stalled", "note.error", "note.maybe_update"):
            self.assertTrue(runner.end_shot_wanted(report([R.OK, R.WARN], [note])), note)

    def test_a_warning_alone_is_not_enough(self):
        self.assertFalse(runner.end_shot_wanted(report([R.OK, R.WARN], ["note.no_task_lines"])))


class SendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def picture(self, name):
        path = os.path.join(self.tmp.name, name)
        Path(path).write_bytes(b"jpg")
        return path

    def test_failed_task_picture_sent_end_picture_dropped(self):
        rep = report([R.OK, R.FAIL, R.OK])
        rep.failure_shots = [("task1", self.picture("task1.jpg"))]
        rep.screenshot = self.picture("end.jpg")
        photos = runner.screenshots_to_send([rep], False, "en")
        self.assertEqual([path for _, path in photos], [rep.failure_shots[0][1]])
        self.assertIn("task1", photos[0][0])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "end.jpg")))

    def test_both_when_the_end_also_went_wrong(self):
        rep = report([R.OK, R.FAIL, R.FAIL])
        rep.failure_shots = [("task1", self.picture("task1.jpg")), ("task2", self.picture("task2.jpg"))]
        rep.screenshot = self.picture("end.jpg")
        photos = runner.screenshots_to_send([rep], False, "zh")
        self.assertEqual(len(photos), 3)
        self.assertIn("失败时的屏幕", photos[0][0])

    def test_stopped_run_sends_nothing(self):
        rep = report([R.FAIL])
        rep.failure_shots = [("task0", self.picture("task0.jpg"))]
        rep.screenshot = self.picture("end.jpg")
        self.assertEqual(runner.screenshots_to_send([rep], True, "en"), [])
        self.assertEqual(os.listdir(self.tmp.name), [])


if __name__ == "__main__":
    unittest.main()
