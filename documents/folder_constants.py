"""Standard document folders provisioned for every client."""

SUPPORTING_DOCUMENTS_SLUG = "supporting-documents"
KYC_DOCUMENTS_SLUG = "kyc-documents"
LEGACY_KYC_SLUG = "kyc"

STANDARD_CLIENT_FOLDER_SLUGS = frozenset(
    {
        SUPPORTING_DOCUMENTS_SLUG,
        KYC_DOCUMENTS_SLUG,
        LEGACY_KYC_SLUG,
    }
)

# Folders whose files may be uploaded from a task before assignees approve it.
EARLY_TASK_UPLOAD_FOLDER_SLUGS = frozenset(
    {
        SUPPORTING_DOCUMENTS_SLUG,
        KYC_DOCUMENTS_SLUG,
        LEGACY_KYC_SLUG,
    }
)
