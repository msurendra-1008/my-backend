import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, password=None, **extra_fields):
        user = self.model(**extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'superadmin')
        return self.create_user(password=password, email=email, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = [
        ('superadmin',       'Super Admin'),
        ('admin',            'Admin'),
        ('employee',         'Employee'),
        ('upa_user',         'UPA User'),
        ('vendor',           'Vendor'),
        ('delivery_partner', 'Delivery Partner'),
    ]

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email       = models.EmailField(unique=True, null=True, blank=True)
    mobile      = models.CharField(max_length=15, unique=True, null=True, blank=True)
    first_name  = models.CharField(max_length=75, blank=True)
    last_name   = models.CharField(max_length=75, blank=True)
    role        = models.CharField(max_length=20, choices=ROLE_CHOICES, default='upa_user')
    upa_id      = models.CharField(max_length=20, unique=True, null=True, blank=True)
    photo       = models.ImageField(upload_to='profiles/', null=True, blank=True)
    is_active   = models.BooleanField(default=True)
    is_staff    = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD  = 'email'
    REQUIRED_FIELDS = ['first_name']
    objects = UserManager()

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-date_joined']

    def __str__(self):
        return self.email or self.mobile or str(self.id)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email or self.mobile or ''

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email or self.mobile or str(self.id)

    def get_short_name(self):
        return self.first_name or self.email or self.mobile or str(self.id)

    # Backward compat
    @property
    def created_at(self):
        return self.date_joined
