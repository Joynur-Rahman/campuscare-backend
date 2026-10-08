import logging
from typing import Optional

logger = logging.getLogger(__name__)

class NotificationService:
    def _send_email(self, to_user_id: str, subject: str, body: str):
        # Stub for sending an email
        logger.info(f"EMAIL -> User {to_user_id}: {subject} - {body}")

    def _send_in_app(self, to_user_id: str, title: str, message: str, link: Optional[str] = None):
        # Stub for sending in-app notification (could be pushed to a 'notifications' table or via websocket)
        logger.info(f"IN-APP -> User {to_user_id}: {title} - {message} (Link: {link})")

    def notify_assignment(self, ticket_id: str, assigned_to: str, assigner_id: str):
        subject = f"Ticket #{ticket_id[:8]} Assigned"
        body = f"You have been assigned to handle ticket {ticket_id}."
        self._send_email(assigned_to, subject, body)
        self._send_in_app(assigned_to, subject, body, link=f"/tickets/{ticket_id}")

    def notify_status_change(self, ticket_id: str, owner_id: str, old_status: str, new_status: str):
        subject = f"Ticket #{ticket_id[:8]} Status Updated"
        body = f"Your ticket status changed from '{old_status}' to '{new_status}'."
        self._send_email(owner_id, subject, body)
        self._send_in_app(owner_id, subject, body, link=f"/tickets/{ticket_id}")

    def notify_resolution(self, ticket_id: str, owner_id: str):
        subject = f"Ticket #{ticket_id[:8]} Resolved"
        body = f"Your ticket has been marked as resolved."
        self._send_email(owner_id, subject, body)
        self._send_in_app(owner_id, subject, body, link=f"/tickets/{ticket_id}")

notification_service = NotificationService()
