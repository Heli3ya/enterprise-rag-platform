from django.contrib.auth.models import AbstractUser
from django.db import models
from departments.models import Department


class User(AbstractUser):
    ROLE_CHOICES = (
        ('Admin', 'Admin'),
        ('Member', 'Member'),
    )

    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        default='Member'
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    def __str__(self):
        return self.username