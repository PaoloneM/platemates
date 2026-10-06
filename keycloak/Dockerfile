# Keycloak with the Family Menu Planner login theme and the Apple identity provider.
# Multi-arch: the upstream image runs on arm64 (Mac, Raspberry Pi) and amd64.

ARG KEYCLOAK_VERSION=26.8.0

FROM quay.io/keycloak/keycloak:${KEYCLOAK_VERSION} AS builder

ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true

# Apple is not a built-in Keycloak provider. Community extension, pinned and checksum-verified
# (sha256 of the release jar, itself checked against the release's published sha512):
# https://github.com/klausbetz/apple-identity-provider-keycloak (1.17.0 supports Keycloak >= 26.5).
# It implements internal Keycloak SPIs: check its compatibility table before upgrading Keycloak.
ADD --chown=keycloak:keycloak \
    --checksum=sha256:4091dee2a1ec9e0771bef4bd46005197d86b0a2b1f25198c41738476b1d102bb \
    https://github.com/klausbetz/apple-identity-provider-keycloak/releases/download/1.17.0/apple-identity-provider-1.17.0.jar \
    /opt/keycloak/providers/apple-identity-provider-1.17.0.jar

COPY --chown=keycloak:keycloak themes/ /opt/keycloak/themes/

RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:${KEYCLOAK_VERSION}
COPY --from=builder /opt/keycloak/ /opt/keycloak/
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
