#!/usr/bin/env python3

import colorsys
import math
import shutil
import statistics
import sys
import threading
from typing import List, Tuple

import alsaseq
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui


class Note(object):
    def __init__(self, on_at: float, off_at: float, note: int, velocity: int) -> None:
        self.on_at: float = on_at
        self.off_at: float = off_at
        self.note: int = note
        self.velocity: int = velocity
        self.comments: List[str] = []

    def duration(self) -> float:
        return self.off_at - self.on_at

    def note_str(self) -> str:
        table = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

        octave = self.note // 12 - 1
        return "{}{}".format(table[self.note % 12], octave)

    def note_color(self) -> Tuple[int, int, int, float]:
        h = ((self.note + 7) % 12) / 12.0
        s = 1.0
        v = 1.0

        octave = self.note // 12 - 1
        if octave == 1:
            v = 0.7
        elif octave == 2:
            v = 0.8
        elif octave == 3:
            v = 0.9
        elif octave == 5:
            s = 0.8
        elif octave == 6:
            s = 0.6
        elif octave == 7:
            s = 0.4
        elif octave == 8:
            s = 0.2

        r, g, b = colorsys.hsv_to_rgb(h, s, v)

        return (int(r * 255), int(g * 255), int(b * 255), int(0.85 * 255))


TIMEOUT_SEC = 1.5


alsaseq.client("Recorder", 1, 0, True)
alsaseq.connectfrom(0, 20, 0)
alsaseq.start()


running = True

data: List[Note] = []
data_updated: bool = False
data_lock = threading.Lock()
data_cv = threading.Condition(data_lock)


class AseqThread(threading.Thread):
    def run(arg):
        def print_summary(name: str, mu: float, pstd: float) -> None:
            print(
                "{}: mean = {:.4f}, pstdev = {:.4f} ({:.2f}%)".format(
                    name, mu, pstd, pstd * 100 / mu
                )
            )

        def make_comment(name: str, val: float, mu: float) -> str:
            delta = val - mu
            return "{} {:.4f} ({:.2f}%)".format(name, delta, delta * 100 / mu)

        def get_intervals(notes: List[Note]) -> List[float]:
            if not notes:
                return []

            intervals = []
            prev = notes[0]
            for cur in notes[1:]:
                intervals.append(cur.on_at - prev.on_at)
                prev = cur

            return intervals

        def show_report(data: List[Note]) -> None:
            if len(data) < 2:
                return

            data_right: List[Note] = []
            data_left: List[Note] = []

            prev = None
            for cur in data:
                if prev and cur.note % 12 == prev.note % 12:
                    if cur.note < prev.note:
                        data_right.append(prev)
                        data_left.append(cur)
                    else:
                        data_right.append(cur)
                        data_left.append(prev)
                    prev = None
                else:
                    prev = cur

            velocities = [x.velocity for x in data]
            durations = [x.duration() for x in data if x.duration() != 0]
            intervals = get_intervals(data)
            intervals_right = get_intervals(data_right)
            intervals_left = get_intervals(data_left)

            mu_vel = statistics.mean(velocities)
            pstd_vel = statistics.pstdev(velocities, mu_vel)

            mu_dur = statistics.mean(durations)
            pstd_dur = statistics.pstdev(durations, mu_dur)

            for note in sorted(
                data, key=lambda x: abs(x.velocity - mu_vel), reverse=True
            )[:3]:
                note.comments.append(make_comment("velocity", note.velocity, mu_vel))

            for note in sorted(
                data, key=lambda x: abs(x.duration() - mu_dur), reverse=True
            )[:3]:
                note.comments.append(make_comment("duration", note.duration(), mu_dur))

            if len(data) * 0.9 > len(data_right) + len(data_left):
                mu_int = statistics.mean(intervals)
                pstd_int = statistics.pstdev(intervals, mu_int)

                for i, interval in sorted(
                    enumerate(intervals), key=lambda x: x[1] - mu_int, reverse=True
                )[:3]:
                    data[i + 1].comments.append(
                        make_comment("interval", interval, mu_int)
                    )
            else:
                mu_int_r = statistics.mean(intervals_right)
                mu_int_l = statistics.mean(intervals_left)
                pstd_int_r = statistics.pstdev(intervals_right, mu_int_r)
                pstd_int_l = statistics.pstdev(intervals_left, mu_int_l)

                for i, interval in sorted(
                    enumerate(intervals_right),
                    key=lambda x: x[1] - mu_int_r,
                    reverse=True,
                )[:3]:
                    data[i + 1].comments.append(
                        make_comment("interval (right)", interval, mu_int_r)
                    )
                for i, interval in sorted(
                    enumerate(intervals_left),
                    key=lambda x: x[1] - mu_int_l,
                    reverse=True,
                )[:3]:
                    data[i + 1].comments.append(
                        make_comment("interval (left)", interval, mu_int_l)
                    )

            for i, note in enumerate(data):
                for comment in note.comments:
                    print("{}: {}: {}".format(i + 1, note.note_str(), comment))

            if len(data) * 0.9 > len(data_right) + len(data_left):
                print_summary("interval", mu_int, pstd_int)
            else:
                print_summary("interval (right)", mu_int_r, pstd_int_r)
                print_summary("interval (left)", mu_int_l, pstd_int_l)

            print_summary("velocity", mu_vel, pstd_vel)
            print_summary("duration", mu_dur, pstd_dur)

        global data, data_updated

        # Skip all old events
        while alsaseq.inputpending():
            alsaseq.input()

        notes_on = {}

        while running:
            event = alsaseq.input()
            timestamp = event[4][0] + event[4][1] / 1000000000.0

            with data_lock:
                if data and not notes_on and timestamp - data[-1].off_at > TIMEOUT_SEC:
                    show_report(data)
                    print("-" * shutil.get_terminal_size().columns)
                    data = []

                if event[0] == alsaseq.SND_SEQ_EVENT_NOTEON:
                    note = Note(timestamp, timestamp, event[7][1], event[7][2])
                    notes_on[note.note] = note
                    data.append(note)
                    data_updated = True
                elif event[0] == alsaseq.SND_SEQ_EVENT_NOTEOFF:
                    try:
                        note = notes_on.pop(event[7][1])
                        note.off_at = timestamp
                        data_updated = True
                    except KeyError:
                        print(data)
                        print(notes_on)
                        continue
                elif event[0] == alsaseq.SND_SEQ_EVENT_CLOCK:
                    if notes_on:
                        for note in notes_on.values():
                            note.off_at = timestamp
                        data_updated = True

                if data_updated:
                    data_cv.notify()


def update():
    global data_updated

    with data_lock:
        if not data_updated:
            if not data_cv.wait(1):
                return None
        data_updated = False
        lis = [(x.on_at, x.velocity, x.duration(), x.note_color()) for x in data]
        lis = list(zip(*lis))
    xmin = lis[0][0]
    xmax = lis[0][-1] + lis[2][-1]
    xdelta = xmax - xmin
    p.setXRange(xmin, xmin + ((math.ceil(xdelta) + 5 - 1) // 5) * 5)
    bg.setOpts(
        x0=list(lis[0]), height=list(lis[1]), width=list(lis[2]), brushes=list(lis[3])
    )


app = QtGui.QApplication([])

pg.setConfigOption("background", "w")
pg.setConfigOption("foreground", "k")

w = QtGui.QMainWindow()
cw = pg.GraphicsLayoutWidget()
w.show()
w.setCentralWidget(cw)
w.setWindowTitle("aseq visualizer")

bg = pg.BarGraphItem(x=[], height=[], width=[], pen=pg.mkPen(style=QtCore.Qt.NoPen))

p = cw.addPlot()
p.setXRange(0, 5, padding=0)
p.setYRange(0, 127, padding=0)
p.addItem(bg)

aseq_thread = AseqThread()
aseq_thread.start()

t = QtCore.QTimer()
t.timeout.connect(update)
t.start(50)

if __name__ == "__main__":
    if (sys.flags.interactive != 1) or not hasattr(QtCore, "PYQT_VERSION"):
        app.exec_()
        running = False
