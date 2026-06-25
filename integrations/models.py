from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class AppDefinition:
    id: str
    name: str
    toolkit_slug: str
    category: str
    description: str
    auth_type: str
    icon: str
    permissions: tuple[str, ...]
    tool_prefixes: tuple[str, ...] = ()

    def public_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("toolkit_slug", None)
        payload.pop("tool_prefixes", None)
        payload["permissions"] = list(self.permissions)
        return payload


APPS: tuple[AppDefinition, ...] = (
    AppDefinition("gmail", "Gmail", "gmail", "Productivity", "Read, draft, and send email.", "OAuth", "gmail", ("Read email", "Draft email", "Send email"), ("GMAIL_",)),
    AppDefinition("outlook", "Outlook", "outlook", "Productivity", "Manage Microsoft email and mailboxes.", "OAuth", "microsoftoutlook", ("Read mail", "Draft mail", "Send mail"), ("OUTLOOK_",)),
    AppDefinition("google-calendar", "Google Calendar", "googlecalendar", "Productivity", "Create and manage calendar events.", "OAuth", "googlecalendar", ("Read calendars", "Create events", "Update events"), ("GOOGLECALENDAR_",)),
    AppDefinition("google-drive", "Google Drive", "googledrive", "Storage", "Search, read, and organize Drive files.", "OAuth", "googledrive", ("Read files", "Create files", "Manage files"), ("GOOGLEDRIVE_",)),
    AppDefinition("onedrive", "OneDrive", "one_drive", "Storage", "Access and organize Microsoft cloud files.", "OAuth", "microsoftonedrive", ("Read files", "Create files", "Manage files"), ("ONE_DRIVE_",)),
    AppDefinition("google-sheets", "Google Sheets", "googlesheets", "Productivity", "Read and update spreadsheets.", "OAuth", "googlesheets", ("Read sheets", "Update cells", "Create sheets"), ("GOOGLESHEETS_",)),
    AppDefinition("microsoft-excel", "Microsoft Excel", "excel", "Productivity", "Work with Excel workbooks and tables.", "OAuth", "microsoftexcel", ("Read workbooks", "Update cells", "Create tables"), ("EXCEL_",)),
    AppDefinition("notion", "Notion", "notion", "Productivity", "Search and update pages and databases.", "OAuth", "notion", ("Read pages", "Create pages", "Update databases"), ("NOTION_",)),
    AppDefinition("slack", "Slack", "slack", "Communication", "Read channels and send workspace messages.", "OAuth", "slack", ("Read channels", "Read messages", "Send messages"), ("SLACK_",)),
    AppDefinition("microsoft-teams", "Microsoft Teams", "microsoft_teams", "Communication", "Work with Teams chats, channels, and meetings.", "OAuth", "microsoftteams", ("Read chats", "Send messages", "Manage meetings"), ("MICROSOFT_TEAMS_",)),
    AppDefinition("github", "GitHub", "github", "Development", "Work with repositories, issues, and pull requests.", "OAuth", "github", ("Read repositories", "Manage issues", "Manage pull requests"), ("GITHUB_",)),
    AppDefinition("gitlab", "GitLab", "gitlab", "Development", "Work with projects, issues, and merge requests.", "OAuth", "gitlab", ("Read projects", "Manage issues", "Manage merge requests"), ("GITLAB_",)),
    AppDefinition("jira", "Jira", "jira", "Development", "Search and update projects and issues.", "OAuth", "jira", ("Read projects", "Create issues", "Update issues"), ("JIRA_",)),
    AppDefinition("linear", "Linear", "linear", "Development", "Manage engineering issues and projects.", "OAuth", "linear", ("Read workspace", "Create issues", "Update issues"), ("LINEAR_",)),
    AppDefinition("supabase", "Supabase", "supabase", "Database", "Manage Supabase projects and database operations.", "API key", "supabase", ("Read projects", "Run queries", "Manage project settings"), ("SUPABASE_",)),
    AppDefinition("postgresql", "PostgreSQL", "postgresql", "Database", "Run approved PostgreSQL database operations.", "Connection credentials", "postgresql", ("Connect to database", "Read data", "Run approved queries"), ("POSTGRESQL_", "POSTGRES_")),
    AppDefinition("dropbox", "Dropbox", "dropbox", "Storage", "Search, read, and organize Dropbox files.", "OAuth", "dropbox", ("Read files", "Create files", "Manage files"), ("DROPBOX_",)),
    AppDefinition("box", "Box", "box", "Storage", "Access and manage Box content.", "OAuth", "box", ("Read files", "Upload files", "Manage files"), ("BOX_",)),
    AppDefinition("discord", "Discord", "discord", "Communication", "Read channels and send Discord messages.", "OAuth", "discord", ("Read servers", "Read channels", "Send messages"), ("DISCORD_",)),
    AppDefinition("telegram", "Telegram", "telegram", "Communication", "Send messages and manage Telegram bot activity.", "API key", "telegram", ("Read updates", "Send messages", "Manage chats"), ("TELEGRAM_",)),
    AppDefinition("openai", "OpenAI", "openai", "AI", "Use connected OpenAI models and resources.", "API key", "openai", ("Use models", "Manage files", "Create responses"), ("OPENAI_",)),
    AppDefinition("anthropic", "Anthropic Claude", "anthropic_administrator", "AI", "Use connected Anthropic administration tools.", "API key", "anthropic", ("Read organization data", "Manage workspaces", "Review usage"), ("ANTHROPIC_", "ANTHROPIC_ADMINISTRATOR_")),
    AppDefinition("gemini", "Google Gemini", "gemini", "AI", "Use Gemini generation and multimodal tools.", "API key", "googlegemini", ("Generate content", "Create embeddings", "Use multimodal tools"), ("GEMINI_",)),
    AppDefinition("perplexity", "Perplexity AI", "perplexityai", "AI", "Run connected Perplexity research queries.", "API key", "perplexity", ("Search the web", "Generate answers", "Use research models"), ("PERPLEXITYAI_",)),
    AppDefinition("webhooks", "Webhooks", "webhook", "Communication", "Send events to approved HTTP endpoints.", "Endpoint secret", "webhook", ("Send webhook events", "Use configured endpoints"), ("WEBHOOK_",)),
)

APP_BY_ID = {app.id: app for app in APPS}
APP_BY_TOOLKIT = {app.toolkit_slug: app for app in APPS}


def get_app(app_id: str) -> Optional[AppDefinition]:
    return APP_BY_ID.get(str(app_id).strip().lower())


def app_for_tool(tool_slug: str) -> Optional[AppDefinition]:
    normalized = str(tool_slug).strip().upper()
    for app in APPS:
        if any(normalized.startswith(prefix) for prefix in app.tool_prefixes):
            return app
    return None


class ConnectAppRequest(BaseModel):
    app_id: str = Field(..., min_length=1, max_length=80)
    return_to: str = Field("/apps", min_length=1, max_length=1000)
    pending_action_id: Optional[str] = Field(None, max_length=180)
    retry: bool = False


class DisconnectAppRequest(BaseModel):
    app_id: str = Field(..., min_length=1, max_length=80)


class PendingActionCreate(BaseModel):
    app_id: str
    workflow_id: Optional[str] = None
    tool_slug: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    account: Optional[str] = None
    agent_name: Optional[str] = None
    chat_id: Optional[str] = None
    return_to: str = "/apps"
