"""Small QRunnable wrapper for one-shot background calls (network, disk scans).

Pattern adapted from the author's calib-fits ``gui/worker.py``
(Worker/WorkerSignals), simplified: the callable's return value arrives on
``result``, any exception as a string on ``error``, ``finished`` always fires.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # surfaced to the UI as a message
            self.signals.error.emit(str(exc))
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


def start_worker(fn, *args, on_result=None, on_error=None, on_finished=None, **kwargs) -> Worker:
    """Convenience: build, wire and enqueue a Worker on the global pool."""
    worker = Worker(fn, *args, **kwargs)
    if on_result:
        worker.signals.result.connect(on_result)
    if on_error:
        worker.signals.error.connect(on_error)
    if on_finished:
        worker.signals.finished.connect(on_finished)
    QThreadPool.globalInstance().start(worker)
    return worker
