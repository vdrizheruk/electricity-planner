from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.middleware.csrf import get_token
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.authentication import BaseAuthentication, SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.models import User


class CsrfOnlyAuthentication(BaseAuthentication):
    """Enforce CSRF on unauthenticated POSTs (login/register) without authenticating."""

    def authenticate(self, request: Request) -> None:
        SessionAuthentication().enforce_csrf(request)
        return None


class CsrfOnlyAuthenticationScheme(OpenApiAuthenticationExtension):  # type: ignore[no-untyped-call]
    target_class = "api.auth.CsrfOnlyAuthentication"
    name = "csrfOnly"

    def get_security_definition(self, auto_schema: object) -> dict[str, str]:
        return {"type": "apiKey", "in": "header", "name": "X-CSRFToken"}


class UserSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ["id", "email", "language"]
        read_only_fields = ["id", "email"]


class CredentialsSerializer(serializers.Serializer[None]):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class CsrfView(APIView):
    """Sets the csrftoken cookie and returns the token for the SPA."""

    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    @extend_schema(responses=inline_serializer("CsrfToken", {"csrfToken": serializers.CharField()}))
    def get(self, request: Request) -> Response:
        return Response({"csrfToken": get_token(request)})


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [CsrfOnlyAuthentication]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"
    serializer_class = CredentialsSerializer

    def post(self, request: Request) -> Response:
        ser = CredentialsSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = User.objects.normalize_email(ser.validated_data["email"])
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError({"email": ["Пользователь уже существует"]})
        try:
            validate_password(ser.validated_data["password"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        user = User.objects.create_user(email=email, password=ser.validated_data["password"])
        login(request._request, user, backend="django.contrib.auth.backends.ModelBackend")
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [CsrfOnlyAuthentication]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"
    serializer_class = CredentialsSerializer

    def post(self, request: Request) -> Response:
        ser = CredentialsSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = authenticate(
            request._request,
            username=ser.validated_data["email"],
            password=ser.validated_data["password"],
        )
        if user is None:
            return Response(
                {"detail": "Неверный email или пароль"}, status=status.HTTP_400_BAD_REQUEST
            )
        login(request._request, user)
        return Response(UserSerializer(user).data)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data)

    def patch(self, request: Request) -> Response:
        ser = UserSerializer(request.user, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)
