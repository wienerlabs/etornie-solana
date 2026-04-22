"""Configurable deadline notification message templates.

Templates are keyed by the number of days (or minutes) remaining until the
deadline.  Each entry provides separate messages for the assigned lawyer and
the client.

All text is in English using plain ASCII characters because WhatsApp API
handles encoding and some carriers have issues with non-ASCII characters.
"""

DEADLINE_TEMPLATES: dict[int, dict[str, str]] = {
    30: {
        "lawyer": (
            "Dear {lawyer_name}, there are 30 days remaining until the deadline "
            "for case file {case_number} ({case_title}). "
            "Please plan the necessary actions. "
            "Deadline: {deadline}"
        ),
        "client": (
            "Dear {client_name}, there are 30 days remaining until the deadline "
            "for your application {case_number} ({case_title}). "
            "Your attorney has been notified. "
            "Deadline: {deadline}"
        ),
    },
    7: {
        "lawyer": (
            "REMINDER: Dear {lawyer_name}, there are 7 days remaining until the deadline "
            "for case file {case_number} ({case_title}). "
            "Urgent action is required. "
            "Deadline: {deadline}"
        ),
        "client": (
            "REMINDER: Dear {client_name}, there are 7 days remaining until the deadline "
            "for your application {case_number} ({case_title}). "
            "Your attorney is following up on the process. "
            "Deadline: {deadline}"
        ),
    },
    1: {
        "lawyer": (
            "URGENT: Dear {lawyer_name}, the deadline for case file "
            "{case_number} ({case_title}) is TOMORROW! "
            "All actions must be completed by today. "
            "Deadline: {deadline}"
        ),
        "client": (
            "URGENT: Dear {client_name}, the deadline for your application "
            "{case_number} ({case_title}) is TOMORROW! "
            "Your attorney is completing the final actions. "
            "Deadline: {deadline}"
        ),
    },
}

MINUTE_TEMPLATES: dict[int, dict[str, str]] = {
    30: {
        "lawyer": (
            "Dear {lawyer_name}, there are 30 minutes remaining until the "
            "final processing time for case file {case_number} ({case_title}). "
            "Final time: {deadline_time}"
        ),
        "client": (
            "Dear {client_name}, there are 30 minutes remaining until the "
            "final processing time for your application {case_number} ({case_title}). "
            "Final time: {deadline_time}"
        ),
    },
    10: {
        "lawyer": (
            "WARNING: Dear {lawyer_name}, there are 10 minutes remaining until the "
            "final processing time for case file {case_number} ({case_title})! "
            "Final time: {deadline_time}"
        ),
        "client": (
            "WARNING: Dear {client_name}, there are 10 minutes remaining until the "
            "final processing time for your application {case_number} ({case_title})! "
            "Final time: {deadline_time}"
        ),
    },
    5: {
        "lawyer": (
            "URGENT: Dear {lawyer_name}, there are 5 minutes remaining until the "
            "final processing time for case file {case_number} ({case_title})! "
            "Take action immediately. "
            "Final time: {deadline_time}"
        ),
        "client": (
            "URGENT: Dear {client_name}, there are 5 minutes remaining until the "
            "final processing time for your application {case_number} ({case_title})! "
            "Final time: {deadline_time}"
        ),
    },
    1: {
        "lawyer": (
            "LAST MINUTE: Dear {lawyer_name}, the final processing time for "
            "case file {case_number} ({case_title}) expires in 1 minute! "
            "Final time: {deadline_time}"
        ),
        "client": (
            "LAST MINUTE: Dear {client_name}, the final processing time for "
            "your application {case_number} ({case_title}) expires in 1 minute! "
            "Final time: {deadline_time}"
        ),
    },
}
