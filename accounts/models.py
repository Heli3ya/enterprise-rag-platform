
from django.contrib.auth.models import AbstractUser
from django.db import models
from departments.models import Department


class User(AbstractUser):
    ROLE_CHOICES = (
        ("Admin", "Admin"),
    )

    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        default="Member",
    )

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    def __str__(self):
        return self.username
