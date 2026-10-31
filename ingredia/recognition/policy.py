"""Process-local admission policy for the explicitly scoped photo trial."""

from collections import OrderedDict, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from ingredia.recognition.errors import FailureCode, RecognitionFailure


class TrialAdmission:
    """Bound concurrent calls, duplicate history and cooldown memory."""

    def __init__(
        self,
        allowed_user_ids: frozenset[int] | None,
        cooldown_seconds: float,
        clock: Callable[[], float],
    ) -> None:
        """Accept an explicit allowlist or None for open trial access."""
        self._allowed = allowed_user_ids
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._last: OrderedDict[int, float] = OrderedDict()
        self._seen: deque[tuple[int, int]] = deque(maxlen=256)
        self._busy = False

    @contextmanager
    def admit(self, user_id: int, message_id: int) -> Iterator[None]:
        """Reserve one provider slot before any download, releasing it on every outcome."""
        self._check_access(user_id)
        self._check_request(user_id, message_id)
        self._remember(user_id, message_id)
        self._busy = True
        try:
            yield
        finally:
            self._busy = False

    def _check_access(self, user_id: int) -> None:
        if self._allowed is not None and user_id not in self._allowed:
            raise RecognitionFailure(FailureCode.FORBIDDEN)

    def _check_request(self, user_id: int, message_id: int) -> None:
        if (user_id, message_id) in self._seen:
            raise RecognitionFailure(FailureCode.DUPLICATE)
        if self._busy:
            raise RecognitionFailure(FailureCode.BUSY)
        elapsed = self._clock() - self._last.get(user_id, float("-inf"))
        if elapsed < self._cooldown:
            raise RecognitionFailure(FailureCode.COOLDOWN)

    def _remember(self, user_id: int, message_id: int) -> None:
        self._seen.append((user_id, message_id))
        self._last[user_id] = self._clock()
        self._last.move_to_end(user_id)
        if len(self._last) > 256:
            self._last.popitem(last=False)
