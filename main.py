#!/usr/bin/env python3

import colorsys
import math
import shutil
import statistics
import sys
import threading
import time

import alsaseq
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui

alsaseq.client("Recorder", 1, 0, True)
alsaseq.connectfrom(0, 20, 0)
alsaseq.start()


running = True

data = []
data_updated = False
data_lock = threading.Lock()
data_cv = threading.Condition(data_lock)


class Note(object):
    timestamp = None
    note = None
    velocity = None
    duration = None
    interval = 0
    interval_one_hand = 0

    def __init__(self, timestamp, note, velocity, duration, interval):
        self.timestamp = timestamp
        self.note = note
        self.velocity = velocity
        self.duration = duration
        self.interval = interval
        self.hand = "u"


def note_to_str(note):
    table = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

    octave = note // 12 - 1
    return "{}{}".format(table[note % 12], octave)


def note_to_color(note):
    h = ((note + 7) % 12) / 12.0
    s = 1.0
    v = 1.0

    octave = note // 12 - 1
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


class AseqThread(threading.Thread):
    def run(arg):
        global data, data_updated

        # Skip all old events
        while alsaseq.inputpending():
            alsaseq.input()

        notes_on = {}

        while running:
            event = alsaseq.input()
            timestamp = event[4][0] + event[4][1] / 1000000000.0

            with data_lock:
                if (
                    data
                    and not notes_on
                    and timestamp - (data[-1][0] + data[-1][3]) > 1.5
                ):
                    data2 = []

                    prev = None
                    for d in data:
                        if not prev:
                            data2.append(Note(d[0], d[1], d[2], d[3], 0))
                        else:
                            data2.append(Note(d[0], d[1], d[2], d[3], d[0] - prev[0]))
                        prev = d

                    prev = None
                    for d in data2:
                        if not prev:
                            prev = d
                            continue
                        if d.note[:-1] == prev.note[:-1]:
                            if d.note[-1] < prev.note[-1]:
                                d.hand = "l"
                                prev.hand = "r"
                            else:
                                d.hand = "r"
                                prev.hand = "l"
                            prev = None
                        else:
                            prev = d

                    prev = None
                    for d in data2:
                        if d.hand == "l":
                            continue
                        if d.hand == "u":
                            prev = None
                            continue
                        if not prev:
                            prev = d
                            continue
                        d.interval_one_hand = d.timestamp - prev.timestamp
                        prev = d

                    prev = None
                    for d in data2:
                        if d.hand == "r":
                            continue
                        if d.hand == "u":
                            prev = None
                            continue
                        if not prev:
                            prev = d
                            continue
                        d.interval_one_hand = d.timestamp - prev.timestamp
                        prev = d

                    velocities = [d.velocity for d in data2]
                    durations = [d.duration for d in data2 if d.duration != 0]
                    intervals = [d.interval for d in data2 if d.interval != 0]
                    rintervals = [
                        d for d in data2 if d.interval_one_hand != 0 and d.hand == "r"
                    ]
                    lintervals = [
                        d for d in data2 if d.interval_one_hand != 0 and d.hand == "l"
                    ]

                    if durations and intervals:
                        mu_vel = statistics.mean(velocities)
                        mu_dur = statistics.mean(durations)
                        mu_int = statistics.mean(intervals)
                        pstd_vel = statistics.pstdev(velocities, mu_vel)
                        pstd_dur = statistics.pstdev(durations, mu_dur)
                        pstd_int = statistics.pstdev(intervals, mu_int)

                        for i, d in enumerate(data2):
                            if not rintervals and not lintervals:
                                if abs(d.interval - mu_int) > pstd_int * 1.5:
                                    print(
                                        "{}: {}: interval {:.4f} ({:.2f}%)".format(
                                            i,
                                            d.note,
                                            d.interval - mu_dur,
                                            (d.interval - mu_int) * 100 / mu_int,
                                        )
                                    )
                            if abs(d.velocity - mu_vel) > pstd_vel * 2:
                                print(
                                    "{}: {}: velocity {:.4f} ({:.2f}%)".format(
                                        i,
                                        d.note,
                                        d.velocity - mu_vel,
                                        (d.velocity - mu_vel) * 100 / mu_vel,
                                    )
                                )
                            if abs(d.duration - mu_dur) > pstd_dur * 2:
                                print(
                                    "{}: {}: duration {:.4f} ({:.2f}%)".format(
                                        i,
                                        d.note,
                                        d.duration - mu_dur,
                                        (d.duration - mu_dur) * 100 / mu_dur,
                                    )
                                )

                        if rintervals:
                            d = [i.interval_one_hand for i in rintervals]
                            mu = statistics.mean(d)
                            pstd = statistics.pstdev(d, mu)
                            print(
                                "interval (right): mean = {:.4f}, pstdev = {:.4f} ({:.2f}%)".format(
                                    mu, pstd, pstd * 100 / mu
                                )
                            )

                        if lintervals:
                            d = [i.interval_one_hand for i in lintervals]
                            mu = statistics.mean(d)
                            pstd = statistics.pstdev(d, mu)
                            print(
                                "interval (left): mean = {:.4f}, pstdev = {:.4f} ({:.2f}%)".format(
                                    mu, pstd, pstd * 100 / mu
                                )
                            )

                        print(
                            "interval: mean = {:.4f}, pstdev = {:.4f} ({:.2f}%)".format(
                                mu_int, pstd_int, pstd_int * 100 / mu_int
                            )
                        )
                        print(
                            "velocity: mean = {:.4f}, pstdev = {:.4f} ({:.2f}%)".format(
                                mu_vel, pstd_vel, pstd_vel * 100 / mu_vel
                            )
                        )
                        print(
                            "duration: mean = {:.4f}, pstdev = {:.4f} ({:.2f}%)".format(
                                mu_dur, pstd_dur, pstd_dur * 100 / mu_dur
                            )
                        )

                    print("-" * shutil.get_terminal_size().columns)

                    data = []

                if event[0] == 6:
                    note = event[7][1]
                    velocity = event[7][2]
                    notes_on[note] = len(data)
                    data.append(
                        (timestamp, note_to_str(note), velocity, 0, note_to_color(note))
                    )
                    data_updated = True
                elif event[0] == 7:
                    note = event[7][1]
                    try:
                        i = notes_on[note]
                    except KeyError:
                        print(data)
                        print(notes_on)
                        continue
                    del notes_on[note]
                    duration = timestamp - data[i][0]
                    data[i] = (data[i][0], data[i][1], data[i][2], duration, data[i][4])
                    data_updated = True
                elif event[0] == 36:
                    for k, v in notes_on.items():
                        duration = timestamp - data[v][0]
                        data[v] = (
                            data[v][0],
                            data[v][1],
                            data[v][2],
                            duration,
                            data[v][4],
                        )
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
        l = list(zip(*data))
    xmin = l[0][0]
    xmax = l[0][-1] + l[3][-1]
    xdelta = xmax - xmin
    p.setXRange(xmin, xmin + ((math.ceil(xdelta) + 5 - 1) // 5) * 5)
    bg.setOpts(x0=list(l[0]), height=list(l[2]), width=list(l[3]), brushes=list(l[4]))


app = QtGui.QApplication([])

pg.setConfigOption("background", "w")
pg.setConfigOption("foreground", "k")

w = QtGui.QMainWindow()
cw = pg.GraphicsLayoutWidget()
w.showMaximized()
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
    import sys

    if (sys.flags.interactive != 1) or not hasattr(QtCore, "PYQT_VERSION"):
        app.exec_()
        running = False
