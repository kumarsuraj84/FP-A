-- fpa_app 006: the exception event check locks the case row (FOR UPDATE), which needs UPDATE privilege the app login deliberately does not have.
-- Run the check as the owner with a pinned search path; it only reads and validates, it never writes.
ALTER FUNCTION fpa_app.exception_event_check() SECURITY DEFINER SET search_path = fpa_app, pg_temp;
