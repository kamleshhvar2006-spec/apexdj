from django.conf import settings
from django.http import HttpResponse


class CorsMiddleware:
    """Optional CORS for /api/. Does nothing unless CORS_ALLOWED_ORIGINS is set (same-origin deployment needs none)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        allowed = settings.CORS_ALLOWED_ORIGINS
        origin = request.headers.get('Origin')
        applies = bool(allowed and origin and request.path.startswith('/api/') and ('*' in allowed or origin in allowed))
        if applies and request.method == 'OPTIONS':
            response = HttpResponse(status=204)  # preflight
        else:
            response = self.get_response(request)
        if applies:
            response['Access-Control-Allow-Origin'] = '*' if '*' in allowed else origin
            response['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, OPTIONS'
            response['Access-Control-Allow-Headers'] = 'Content-Type, X-Apex-Token'
            response['Access-Control-Max-Age'] = '600'
            response['Vary'] = 'Origin'
        return response
