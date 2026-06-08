"""Settings hub cards — links to existing setup screens (no new business logic)."""

from __future__ import annotations

from dataclasses import dataclass

from .feature_flags import documents_module_enabled, task_module_enabled


@dataclass(frozen=True)
class SettingsCard:
    title: str
    description: str
    url_name: str
    icon: str
    icon_bg: str = "settings-icon-blue"


@dataclass(frozen=True)
class SettingsSection:
    title: str
    cards: tuple[SettingsCard, ...]


def _user_cards(user) -> tuple[SettingsCard, ...]:
    cards: list[SettingsCard] = []
    if user.is_superuser or user.has_perm("core.view_employee"):
        cards.append(
            SettingsCard(
                title="Users",
                description="Add or edit users, access groups, passwords, and branch access.",
                url_name="user_list",
                icon="bi-person-circle-fill",
                icon_bg="settings-icon-blue",
            )
        )
    if user.is_superuser or user.has_perm("core.view_group"):
        cards.append(
            SettingsCard(
                title="Access groups",
                description="Create or edit permission groups and control what users can do.",
                url_name="user_group_list",
                icon="bi-shield-lock-fill",
                icon_bg="settings-icon-purple",
            )
        )
    return tuple(cards)


def _client_setup_cards(user) -> tuple[SettingsCard, ...]:
    cards: list[SettingsCard] = []
    if user.is_superuser or user.has_perm("masters.view_clienttype"):
        cards.append(
            SettingsCard(
                title="Client types",
                description="Define client types, PAN mandatory, and task submit rules when PAN is not applicable.",
                url_name="client_type_list",
                icon="bi-diagram-3-fill",
                icon_bg="settings-icon-green",
            )
        )
    if user.is_superuser or user.has_perm("masters.view_clientgroup"):
        cards.append(
            SettingsCard(
                title="Client groups",
                description="Add, edit, or bulk upload client groups (Group Master).",
                url_name="client_group_list",
                icon="bi-collection-fill",
                icon_bg="settings-icon-teal",
            )
        )
    if (
        user.is_superuser
        or user.has_perm("masters.view_portalname")
        or user.has_perm("masters.add_portalname")
    ):
        cards.append(
            SettingsCard(
                title="Portals list",
                description="Portal names (GST, MCA, etc.) used in password management.",
                url_name="portal_name_list",
                icon="bi-globe2",
                icon_bg="settings-icon-orange",
            )
        )
    return tuple(cards)


def _tasks_setup_cards(user) -> tuple[SettingsCard, ...]:
    if not task_module_enabled():
        return ()
    cards: list[SettingsCard] = []
    if user.is_superuser or user.has_perm("tasks.view_taskgroup"):
        cards.append(
            SettingsCard(
                title="Task groups",
                description="Organise task masters into groups; bulk upload supported.",
                url_name="task_group_list",
                icon="bi-folder-fill",
                icon_bg="settings-icon-indigo",
            )
        )
    if user.is_superuser or user.has_perm("tasks.view_taskmaster"):
        cards.append(
            SettingsCard(
                title="Task masters",
                description="Define recurring rules, checklists, and default fees for new tasks.",
                url_name="task_master_list",
                icon="bi-bookmark-star-fill",
                icon_bg="settings-icon-amber",
            )
        )
    if user.is_superuser:
        cards.append(
            SettingsCard(
                title="Manage task data",
                description="Delete assigned tasks only (keep masters) or remove task masters and groups.",
                url_name="task_data_manage",
                icon="bi-trash3-fill",
                icon_bg="settings-icon-pink",
            )
        )
    return tuple(cards)


def _documents_setup_cards(user) -> tuple[SettingsCard, ...]:
    if not documents_module_enabled():
        return ()
    if not (
        user.is_superuser
        or user.has_perm("documents.manage_document_templates")
    ):
        return ()
    cards: tuple[SettingsCard, ...] = (
        SettingsCard(
            title="Folder creation",
            description="Standard document folders (e.g. Financials, KYC). New folders can only be added here.",
            url_name="document_folder_template_list",
            icon="bi-folder-plus",
            icon_bg="settings-icon-indigo",
        ),
        SettingsCard(
            title="File creation",
            description="Allowed file types per folder, extensions, FY rules, and auto-naming templates.",
            url_name="document_type_template_list",
            icon="bi-file-earmark-plus",
            icon_bg="settings-icon-teal",
        ),
    )
    if task_module_enabled():
        cards = (
            *cards,
            SettingsCard(
                title="Task → folder links",
                description="Map task types to document folders. All file types in a linked folder appear on that task.",
                url_name="task_document_mapping_list",
                icon="bi-link-45deg",
                icon_bg="settings-icon-violet",
            ),
        )
    return cards


def _billing_setup_cards(user) -> tuple[SettingsCard, ...]:
    cards: list[SettingsCard] = []
    if user.is_superuser or user.has_perm("masters.view_expensecategory"):
        cards.append(
            SettingsCard(
                title="Expense categories",
                description="Categories used on MIS expense entries (e.g. stationery, travel).",
                url_name="expense_category_list",
                icon="bi-tags-fill",
                icon_bg="settings-icon-pink",
            )
        )
    return tuple(cards)


def _general_setup_cards(user) -> tuple[SettingsCard, ...]:
    if not user.is_superuser:
        return ()
    return (
        SettingsCard(
            title="Company branding",
            description="Set your firm name and logo shown above CA Office Suite in the sidebar and login page.",
            url_name="site_settings_edit",
            icon="bi-building",
            icon_bg="settings-icon-blue",
        ),
    )


def build_settings_sections(user) -> list[SettingsSection]:
    sections: list[SettingsSection] = []
    general_cards = _general_setup_cards(user)
    if general_cards:
        sections.append(SettingsSection(title="General", cards=general_cards))
    user_cards = _user_cards(user)
    if user_cards:
        sections.append(SettingsSection(title="User", cards=user_cards))
    client_cards = _client_setup_cards(user)
    if client_cards:
        sections.append(SettingsSection(title="Client", cards=client_cards))
    task_cards = _tasks_setup_cards(user)
    if task_cards:
        sections.append(SettingsSection(title="Tasks", cards=task_cards))
    doc_cards = _documents_setup_cards(user)
    if doc_cards:
        sections.append(SettingsSection(title="Documents", cards=doc_cards))
    billing_cards = _billing_setup_cards(user)
    if billing_cards:
        sections.append(SettingsSection(title="Billing", cards=billing_cards))
    return sections


def user_may_open_settings(user) -> bool:
    return bool(build_settings_sections(user))
