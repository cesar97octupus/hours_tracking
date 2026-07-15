from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

_pool = QThreadPool.globalInstance()
_active_workers: set = set()  # keeps workers alive until their signal fires;
                               # QThreadPool only holds a C++-side reference


class _WorkerSignals(QObject):
    success = Signal(object)
    error = Signal(Exception)


class _Worker(QRunnable):
    def __init__(self, fn, args, kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = _WorkerSignals()

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 - forwarded to the UI thread via signal
            self._emit(self.signals.error, exc)
        else:
            self._emit(self.signals.success, result)

    @staticmethod
    def _emit(signal, value) -> None:
        try:
            signal.emit(value)
        except RuntimeError:
            # The Qt objects were already torn down (app quit while this
            # worker was still in flight, e.g. a slow DNS lookup). Nothing
            # left to notify — drop it.
            pass


def run_async(fn, *args, on_success=None, on_error=None, **kwargs) -> _Worker:
    """Run fn(*args, **kwargs) on a QThreadPool thread; on_success(result) or
    on_error(exc) is invoked back on the Qt main thread. Never call blocking
    I/O (OdooClient methods) directly from a UI event handler — always go
    through this."""
    worker = _Worker(fn, args, kwargs)
    _active_workers.add(worker)

    def _cleanup(*_args):
        _active_workers.discard(worker)

    if on_success:
        worker.signals.success.connect(on_success)
    if on_error:
        worker.signals.error.connect(on_error)
    worker.signals.success.connect(_cleanup)
    worker.signals.error.connect(_cleanup)

    _pool.start(worker)
    return worker
