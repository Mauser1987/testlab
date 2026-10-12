"""Who may perform the controlled actions (stabilization decision S3): issue and cancel a TCN,
finalize a Test Result (M2E), undo a manual-log import (M2F), issue report documents and revise a
final Result (M2F-B).

M1: any active, logged-in user may issue and cancel (M1 spec §4 "Approval:
none in M1"); finalizing follows the same rule. Every check of these actions
goes through this module, so a later distinction — e.g. a Django group or permission for users allowed to
issue controlled TCNs, besides ordinary engineers and administrators —
changes this module only, not the views, services or the domain model.
"""


def can_issue_tcn(user):
    return user.is_authenticated and user.is_active


def can_cancel_tcn(user):
    return can_issue_tcn(user)


def can_finalize_result(user):
    """Finalize a Test Result and its Test Run Report: the same controlled-record rule as issuing a TCN."""
    return can_issue_tcn(user)


def can_undo_log_import(user):
    """Undo an imported Excel manual log (it removes recorded evidence): the rule of finalizing a Result."""
    return can_finalize_result(user)


def can_issue_report(user):
    """Issue, re-issue or withdraw a controlled report document (M2F-B): initially the rule of finalizing."""
    return can_finalize_result(user)


def can_revise_result(user):
    """Open a new revision of a final Test Result (M2F-B2): initially the rule of finalizing."""
    return can_finalize_result(user)
