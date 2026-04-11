# questions.md

## 1. Delivery path: Docker acceptance vs. Windows MSI distribution

### The Gap

The original prompt requires a signed Windows `.msi` installer, but the clarified project direction says `.msi` delivery is **not necessary for current acceptance** and Docker is the required containerization and acceptance path.

### The Interpretation

Treat Docker as the real acceptance and validation workflow for this project. The desktop application must still be implemented as a Windows-oriented PyQt application, but MSI packaging is not a current deliverable gate. Instead, the repository must include honest documentation describing how someone could later build an `.msi` and handle certificate-based signing if the organization chooses to ship a native Windows installer.

### Proposed Implementation

Make `repo/docker-compose.yml`, `repo/backend/Dockerfile`, `repo/README.md`, and all runtime/service configuration the acceptance-critical path. Add `docs/windows-packaging.md` with a step-by-step future-build guide covering packaging prerequisites, example build flow, WiX or equivalent installer authoring options, and code-signing steps that clearly identify certificate material as an external dependency when unavailable.

## 2. Certificate ownership and signing workflow for future MSI builds

### The Gap

The clarified direction removes `.msi` from current acceptance, but future Windows-native distribution may still require installer and executable signing. The owner of the certificate, the signing environment, and the approved signing workflow are still unspecified.

### The Interpretation

Do not block implementation on code-signing details. Assume certificate material is organization-owned and external to the repository. Document the expected insertion points for signing commands and the release-time prerequisites, but do not claim signed MSI support is active unless the repo actually contains the required assets and instructions.

### Proposed Implementation

Document a future signing workflow in `docs/windows-packaging.md` with placeholders for certificate location, signing tool invocation, timestamp server configuration, and release ownership. Keep secrets and certificate files out of source control. Provide packaging hooks or examples only where they are truthful and non-misleading.

## 3. Barcode scanner input mode

### The Gap

The prompt says relocations and inventory actions may use manual input or USB barcode scanner input, but it does not define whether scanners behave as keyboard-wedge devices or require deeper device-specific integration.

### The Interpretation

Assume the minimum supported scanner mode is keyboard-wedge input that behaves like fast typed text into focused fields. Preserve a device-source flag so the system can distinguish manual entry from scanner-assisted entry, and keep the UI/service boundaries extensible if district hardware later requires vendor-specific adapters.

### Proposed Implementation

Model `device_source` as an enum with at least `manual` and `usb_scanner`. Build the initial capture path around standard text input workflows optimized for keyboard wedge scanners, with validation, debounce-safe handling, and audit persistence of the source. Keep scanner parsing isolated behind an input adapter abstraction for future extension.

## 4. LAN shared-folder integration assumptions

### The Gap

The prompt requires outbound webhook-style events written to a LAN-shared folder, but it does not specify the exact network-share conventions, file naming contract, retry expectations, or downstream acknowledgment rules.

### The Interpretation

Assume a writable SMB/UNC-style shared folder path is configured per environment and that outbound event delivery is one-way file emission unless a downstream acknowledgment contract is later specified. Delivery must be durable, auditable, and retry-aware without relying on internet services.

### Proposed Implementation

Implement an outbound event writer that writes signed event payload files to a configured shared-folder path, records success/failure metadata, retries transient write failures with backoff, and preserves an event delivery ledger for audit and troubleshooting. Document filename conventions and retention defaults in the API/design docs, and keep them configurable.

## 5. Offline update-package trust model

### The Gap

The prompt requires offline package import with rollback to the prior build retained locally, but it does not define the trust mechanism for update packages, such as manifest signatures, checksum validation, certificate pinning, or operator approval rules.

### The Interpretation

Assume update packages must be validated before import using a manifest plus integrity checks, and that full trust policy details are environment-specific unless later provided. The implementation should support a secure, auditable validation path without pretending a concrete enterprise signing pipeline exists when it has not been supplied.

### Proposed Implementation

Model update packages with a versioned manifest, checksum/integrity metadata, import audit records, and retained rollback references. Implement a validation service that can verify package integrity and reject malformed or mismatched manifests. Document where stronger trust inputs, such as signed manifests or enterprise certificate validation, would plug in later.

## 6. Reviewer/approver policy detail granularity

### The Gap

The prompt establishes Draft → In Review → Published/Unpublished plus reviewer notes and Reviewer/Approver responsibilities, but it does not fully define whether review and approval are always the same role action, whether dual control is required, or whether certain resource categories need stricter publishing rules.

### The Interpretation

Assume a pragmatic single-stage controlled review workflow for the initial implementation: authorized reviewer/approver users can move items through the defined states with required notes and immutable audit entries. Keep the policy engine extensible so stricter separation-of-duties or content-category rules can be added later without schema churn.

### Proposed Implementation

Represent review transitions as explicit domain policies with role checks, note requirements, and audit events. Use a workflow configuration layer so future dual-approval or category-specific gating can be introduced through configuration and policy services rather than rewriting core persistence structures.

## 7. Optional MSI packaging complexity and external signing dependency

### The Gap

The original prompt requires a signed Windows .msi installer, but the clarified delivery direction says Docker is sufficient for current acceptance. It remains unclear whether a real .msi build should still be implemented now, even though doing so introduces additional packaging complexity, Windows-specific build steps, and likely an external code-signing dependency.

### The Interpretation

Treat signed .msi packaging as out of scope for the current acceptance path unless it is explicitly re-promoted to a required deliverable. Assume a future Windows-native installer is feasible, but that it depends on organization-provided signing materials and additional packaging validation that should not block the current Docker-based acceptance workflow.

### Proposed Implementation

Keep the application packaging-friendly and document a future .msi build path in docs/windows-packaging.md. Do not claim signed MSI support as implemented unless the repository actually contains the packaging assets, tested installer workflow, and organization-provided certificate/signing process needed to produce it truthfully.
