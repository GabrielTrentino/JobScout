import unittest

from jobscout.overlay import MARGIN, Area, snap

SCREEN = Area(0, 0, 1920, 1040)


def bubble_at(right: int, bottom: int, size: int = 72) -> Area:
    return Area(right - size, bottom - size, right, bottom)


class SnapTest(unittest.TestCase):
    def test_near_corner_goes_back_to_default(self):
        self.assertIsNone(snap(SCREEN, bubble_at(1880, 1000), 1.0))
        self.assertIsNone(snap(SCREEN, bubble_at(1930, 1050), 1.0))

    def test_near_right_edge_sticks_to_it_keeping_height(self):
        self.assertEqual(snap(SCREEN, bubble_at(1890, 500), 1.0), (1920 - MARGIN, 500))

    def test_elsewhere_stays_where_dropped(self):
        self.assertEqual(snap(SCREEN, bubble_at(900, 400), 1.0), (900, 400))

    def test_distances_follow_the_scale(self):
        self.assertEqual(snap(SCREEN, bubble_at(1850, 500), 1.0), (1850, 500))
        self.assertEqual(snap(SCREEN, bubble_at(1850, 500), 2.0), (1920 - 2 * MARGIN, 500))


if __name__ == "__main__":
    unittest.main()
