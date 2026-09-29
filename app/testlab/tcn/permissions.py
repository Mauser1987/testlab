"""Who may perform the controlled TCN actions (stabilization decision S3).

M1: any active, logged-in user may issue and cancel (M1 spec §4 "Approval:
none in M1"). Every check of these actions goes through this module, so a
later distinction — e.g. a Django group or permission for users allowed to
issue controlled TCNs, besides ordinary engineers and administrators —
changes this module only, not the views, services or the domain model.
"""


def can_issue_tcn(user):
    return user.is_authenticated and user.is_active


def can_cancel_tcn(user):
    return can_issue_tcn(user)
