from django.contrib.auth.mixins import UserPassesTestMixin


class StaffRequiredMixin(UserPassesTestMixin):
    """Limit a class-based view to staff: anonymous users go to login, everyone else gets a 403."""

    def test_func(self):
        return self.request.user.is_staff
