import random
import string


def generate_upa_id():
    from accounts.models import User
    while True:
        code = 'UPA-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not User.objects.filter(upa_id=code).exists():
            return code
