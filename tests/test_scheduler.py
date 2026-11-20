import unittest
from datetime import datetime, timezone

from app import server
from app.server import SyncSchedule


class SyncScheduleTests(unittest.TestCase):
    def test_local_time_uses_system_timezone(self):
        expected = datetime.fromtimestamp(0, timezone.utc).astimezone().isoformat(timespec='seconds')
        self.assertEqual(server.local_time(0), expected)

    def test_first_run_waits_full_interval_after_startup(self):
        settings = {'root': '/media/Gallery', 'interval_minutes': 5}
        schedule = SyncSchedule(settings, 1000)
        self.assertEqual(schedule.deadline, 1300)
        self.assertFalse(schedule.due(settings, 1299))
        self.assertTrue(schedule.due(settings, 1300))
        schedule.complete(1304)
        self.assertEqual(schedule.deadline, 1604)

    def test_enabling_or_changing_schedule_starts_new_interval(self):
        off = {'root': '/media/Gallery', 'interval_minutes': 0}
        every_five = {'root': '/media/Gallery', 'interval_minutes': 5}
        another_source = {'root': '/media/Other', 'interval_minutes': 5}
        schedule = SyncSchedule(off, 1000)
        self.assertIsNone(schedule.deadline)
        self.assertFalse(schedule.due(every_five, 100000))
        self.assertEqual(schedule.deadline, 100300)
        self.assertFalse(schedule.due(another_source, 100200))
        self.assertEqual(schedule.deadline, 100500)
        self.assertFalse(schedule.due(another_source, 100499))
        self.assertTrue(schedule.due(another_source, 100500))


if __name__ == '__main__':
    unittest.main()
