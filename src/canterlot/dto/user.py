from pydantic import BaseModel, Field, field_validator, model_validator

from canterlot.models.user import PersonNameStr, UserModel, UsernameStr


class UpdateProfileRequest(BaseModel):
    name: PersonNameStr | None = None
    username: UsernameStr | None = None

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, v: str | None) -> str | None:
        return v.lower() if v is not None else v

    @model_validator(mode="after")
    def check_at_least_one_field_provided(self) -> "UpdateProfileRequest":
        if self.name is None and self.username is None:
            raise ValueError("At least one of name or username must be provided.")
        return self


class UserProfileResponse(BaseModel):
    name: PersonNameStr
    username: UsernameStr

    @classmethod
    def from_model(cls, user: UserModel) -> "UserProfileResponse":
        return cls(name=user.name, username=user.username)


class ChangePasswordRequest(BaseModel):
    current_password: str | None = Field(default=None, min_length=6, examples=["old_super_secret_password_456"])
    new_password: str = Field(..., min_length=6, examples=["new_super_secret_password_456"])
