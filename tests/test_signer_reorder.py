"""
Reordering signers, as pure logic.

The list order becomes `signerIndex`, 1-based, which on a SEQUENTIAL send is
who gets asked first. The subtle requirement is not the swap — it is that the
selection follows the *person*, so a second click moves the same signer again
rather than starting to shuffle whoever swapped into that row.
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pythonpath"))


class FakeList(object):
    """The two things _move_signer uses from the dialog."""

    def __init__(self, index):
        self.index = index
        self.enabled = {}

    def selected_index(self, _name):
        return self.index

    def select(self, _name, index):
        self.index = index

    def enable(self, name, value):
        self.enabled[name] = value


def move(signers, index, delta):
    """Mirror of dialogs._move_signer, which needs UNO to import."""
    dialog = FakeList(index)
    target = index + delta
    if index < 0 or target < 0 or target >= len(signers):
        return signers, index
    signers[index], signers[target] = signers[target], signers[index]
    dialog.select("signers", target)
    return signers, dialog.index


def names(signers):
    return [s["name"] for s in signers]


def people(*name_list):
    return [{"name": n, "email": "%s@x.com" % n.lower()} for n in name_list]


def test_moving_down_swaps_with_the_next_signer():
    signers, index = move(people("A", "B", "C", "D"), 1, 1)
    assert names(signers) == ["A", "C", "B", "D"]


def test_moving_up_swaps_with_the_previous_signer():
    signers, index = move(people("A", "B", "C", "D"), 2, -1)
    assert names(signers) == ["A", "C", "B", "D"]


def test_the_selection_follows_the_person_not_the_row():
    # Two clicks of Descer must move the SAME signer twice.
    signers = people("A", "B", "C", "D")
    signers, index = move(signers, 0, 1)
    assert names(signers) == ["B", "A", "C", "D"]
    signers, index = move(signers, index, 1)
    assert names(signers) == ["B", "C", "A", "D"]
    # A moved from first to third, rather than A and then B being shuffled.
    assert signers[index]["name"] == "A"


def test_moving_off_either_end_does_nothing():
    original = people("A", "B", "C")
    signers, index = move(list(original), 0, -1)
    assert names(signers) == ["A", "B", "C"]
    signers, index = move(list(original), 2, 1)
    assert names(signers) == ["A", "B", "C"]


def test_moving_with_nothing_selected_does_nothing():
    signers, index = move(people("A", "B"), -1, 1)
    assert names(signers) == ["A", "B"]


def test_a_full_reorder_of_four_signers():
    # The case that prompted this: four entered, the last one belongs first.
    signers = people("A", "B", "C", "D")
    index = 3
    for _ in range(3):
        signers, index = move(signers, index, -1)
    assert names(signers) == ["D", "A", "B", "C"]
