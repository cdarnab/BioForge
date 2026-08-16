import pytest

from bioforge.biophysics import (
    CdrSpans,
    aggregation_propensity,
    n_glyc_sequons,
    net_charge_at_ph7,
    sequence_metrics,
    surface_hydrophobicity,
    unpaired_cysteines,
    validate_sequence,
)

SPANS = CdrSpans(cdr1=(0, 4), cdr2=(4, 8), cdr3=(8, 16))


def test_rejects_non_standard_residues():
    with pytest.raises(ValueError, match="non-standard"):
        validate_sequence("QVQLXBZ")


def test_net_charge_is_exact():
    assert net_charge_at_ph7("KKK") == 3.0
    assert net_charge_at_ph7("DDD") == -3.0
    assert net_charge_at_ph7("KD") == 0.0
    assert net_charge_at_ph7("GGGG") == 0.0
    # Histidine is only partly protonated at pH 7.
    assert net_charge_at_ph7("H") == 0.09


def test_unpaired_cysteines_allows_the_conserved_pair():
    assert unpaired_cysteines("GGCGGCGG") == 0
    assert unpaired_cysteines("GGCGGCGGC") == 1
    assert unpaired_cysteines("GGGG") == 0
    assert unpaired_cysteines("GGCGG") == 1


def test_n_glyc_sequon_motif():
    assert n_glyc_sequons("NAS") == 1
    assert n_glyc_sequons("NAT") == 1
    # Proline at position 2 blocks the sequon.
    assert n_glyc_sequons("NPS") == 0
    assert n_glyc_sequons("NAG") == 0
    assert n_glyc_sequons("NASNAT") == 2


def test_hydrophobicity_ordering_matches_the_scale():
    hydrophobic = "IIIIVVVVLLLLFFFF"
    hydrophilic = "RRRRDDDDKKKKEEEE"
    assert surface_hydrophobicity(hydrophobic, SPANS) > surface_hydrophobicity(hydrophilic, SPANS)
    assert 0.0 <= surface_hydrophobicity(hydrophilic, SPANS) <= 1.0
    assert 0.0 <= surface_hydrophobicity(hydrophobic, SPANS) <= 1.0


def test_aggregation_propensity_detects_a_hydrophobic_patch():
    patchy = "GGGGSSSSIIIIILLL"
    clean = "GGGGSSSSRDRDRDRD"
    assert aggregation_propensity(patchy, SPANS) > aggregation_propensity(clean, SPANS)
    assert aggregation_propensity(clean, SPANS) >= 0.0


def test_a_fully_hydrophilic_sequence_has_zero_aggregation_propensity():
    assert aggregation_propensity("RRRRDDDDKKKKEEEE", SPANS) == 0.0


def test_metrics_are_deterministic():
    sequence = "GRTFSLYDISWSGGSTAAIRGYLSDSDY"
    spans = CdrSpans(cdr1=(0, 8), cdr2=(8, 16), cdr3=(16, 28))
    first = sequence_metrics(sequence, spans)
    for _ in range(5):
        assert sequence_metrics(sequence, spans) == first


def test_metrics_change_when_the_sequence_changes():
    spans = CdrSpans(cdr1=(0, 8), cdr2=(8, 16), cdr3=(16, 28))
    parent = "GRTFSLYDISWSGGSTAAIRGYLSDSDY"
    child = parent.replace("AAIRGYLS", "SASRGYNS")
    assert sequence_metrics(parent, spans) != sequence_metrics(child, spans)


def test_every_metric_is_finite_and_named():
    spans = CdrSpans(cdr1=(0, 8), cdr2=(8, 16), cdr3=(16, 28))
    metrics = sequence_metrics("GRTFSLYDISWSGGSTAAIRGYLSDSDY", spans)
    assert set(metrics) == {
        "surface_hydrophobicity",
        "aggregation_propensity",
        "net_charge_at_ph7",
        "unpaired_cysteines",
        "n_glyc_sequons",
    }
    for value in metrics.values():
        assert isinstance(value, float)
        assert value == value  # not NaN
