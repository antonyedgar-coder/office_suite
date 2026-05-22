"""Settings hub cards — links to existing setup screens (no new business logic)."""

from __future__ import annotations

from dataclasses import dataclass

from .feature_flags import task_module_enabled


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
    return tuple(cards)


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


def build_settings_sections(user) -> list[SettingsSection]:
    sections: list[SettingsSection] = []
    user_cards = _user_cards(user)
    if user_cards:
        sections.append(SettingsSection(title="User", cards=user_cards))
    client_cards = _client_setup_cards(user)
    if client_cards:
        sections.append(SettingsSection(title="Client", cards=client_cards))
    task_cards = _tasks_setup_cards(user)
    if task_cards:
        sections.append(SettingsSection(title="Tasks", cards=task_cards))
    billing_cards = _billing_setup_cards(user)
    if billing_cards:
        sections.append(SettingsSection(title="Billing", cards=billing_cards))
    return sections


def user_may_open_settings(user) -> bool:
    return bool(build_settings_sections(user))
