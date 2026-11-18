import stat
from pathlib import Path

from herdr_lark.pairing import (
    MAX_PAIR_FAILURES,
    PAIRING_TTL_SECONDS,
    OwnerStore,
    Pairing,
    PairingStore,
    attempt,
)

P = Pairing("123456", expires_at=1000.0)


def test_unarmed_pairing_never_pairs():
    assert attempt(None, "123456", 0.0) == (None, "unarmed")


def test_correct_code_pairs_and_disarms():
    assert attempt(P, " 123456 ", 999.0) == (None, "paired")


def test_expired_code_is_rejected_even_if_correct_and_disarms():
    assert attempt(P, "123456", 1000.0) == (None, "expired")


def test_five_wrong_codes_disarm_and_the_right_code_after_that_cannot_pair():
    p: Pairing | None = P
    for i in range(MAX_PAIR_FAILURES - 1):
        p, outcome = attempt(p, "000000", 1.0)
        assert outcome == "wrong" and p is not None and p.failures == i + 1
    p, outcome = attempt(p, "000000", 1.0)
    assert (p, outcome) == (None, "exhausted")
    assert attempt(p, "123456", 1.0) == (None, "unarmed")


def test_arm_writes_0600_six_digit_code_expiring_in_ten_minutes(tmp_path: Path):
    store = PairingStore(tmp_path / "cfg" / "pairing.json")
    p = store.arm(now=100.0)
    assert len(p.code) == 6 and p.code.isdigit()
    assert p.expires_at == 100.0 + PAIRING_TTL_SECONDS == 700.0
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert store.load() == p


def test_garbage_pairing_file_is_deleted_and_treated_as_unarmed(tmp_path: Path):
    store = PairingStore(tmp_path / "pairing.json")
    store.path.write_text("{oops")
    assert store.load() is None
    assert not store.path.exists()


def test_owner_file_roundtrip_mode_and_delete(tmp_path: Path):
    owner = OwnerStore(tmp_path / "owner")
    assert owner.read() is None
    owner.write("ou_abc")
    assert owner.read() == "ou_abc"
    assert stat.S_IMODE(owner.path.stat().st_mode) == 0o600
    owner.delete()
    owner.delete()
    assert owner.read() is None


def test_owner_file_takes_first_line_only_and_empty_means_unpaired(tmp_path: Path):
    p = tmp_path / "owner"
    p.write_text("ou_abc\nignored\n")
    assert OwnerStore(p).read() == "ou_abc"
    p.write_text("\n")
    assert OwnerStore(p).read() is None
