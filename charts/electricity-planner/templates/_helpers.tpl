{{- define "ep.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "ep.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "ep.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: {{ include "ep.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}

{{/* component selector labels: call with (dict "ctx" . "component" "backend") */}}
{{- define "ep.selector" -}}
app.kubernetes.io/name: {{ include "ep.name" .ctx }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{- define "ep.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "ep.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "ep.backendImage" -}}
{{ .Values.backend.image.repository }}:{{ .Values.backend.image.tag | default .Chart.AppVersion }}
{{- end }}

{{- define "ep.frontendImage" -}}
{{ .Values.frontend.image.repository }}:{{ .Values.frontend.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/* Name of the chart-managed Secret. */}}
{{- define "ep.secretName" -}}
{{ include "ep.fullname" . }}
{{- end }}

{{/* Secret that holds DJANGO_SECRET_KEY. */}}
{{- define "ep.appSecret" -}}
{{ .Values.secret.existingSecret | default (include "ep.secretName" .) }}
{{- end }}

{{/* Secret that holds the external DATABASE_URL. */}}
{{- define "ep.dbSecret" -}}
{{ .Values.database.existingSecret | default (include "ep.appSecret" .) }}
{{- end }}

{{/* Secret that holds the built-in database password. */}}
{{- define "ep.pgSecret" -}}
{{ .Values.postgresql.auth.existingSecret | default (include "ep.appSecret" .) }}
{{- end }}

{{/* Which keys the chart-managed Secret carries ("true" when it has the key). */}}
{{- define "ep.managedAppKey" -}}{{- if not .Values.secret.existingSecret -}}true{{- end -}}{{- end }}
{{- define "ep.managedPgKey" -}}{{- if and .Values.postgresql.enabled (not .Values.postgresql.auth.existingSecret) (not .Values.secret.existingSecret) -}}true{{- end -}}{{- end }}
{{- define "ep.managedDbKey" -}}{{- if and (not .Values.postgresql.enabled) .Values.database.url (not .Values.database.existingSecret) (not .Values.secret.existingSecret) -}}true{{- end -}}{{- end }}
{{- define "ep.managesSecret" -}}{{- if or (include "ep.managedAppKey" .) (include "ep.managedPgKey" .) (include "ep.managedDbKey" .) -}}true{{- end -}}{{- end }}

{{/* Hook events of the migration Job: the database and the Secret must exist first on install. */}}
{{- define "ep.migrateHooks" -}}
{{- if or .Values.postgresql.enabled (include "ep.managesSecret" .) -}}post-install,pre-upgrade{{- else -}}pre-install,pre-upgrade{{- end -}}
{{- end }}

{{/* Public hosts: ingress hosts. */}}
{{- define "ep.allowedHosts" -}}
{{- $h := concat (list "localhost" "$(POD_IP)") .Values.ingress.hosts .Values.config.allowedHosts -}}
{{- join "," (uniq $h) -}}
{{- end }}

{{- define "ep.csrfOrigins" -}}
{{- if .Values.config.csrfTrustedOrigins -}}
{{- join "," .Values.config.csrfTrustedOrigins -}}
{{- else -}}
{{- $scheme := ternary "https" "http" (not (empty .Values.ingress.tls)) -}}
{{- $o := list -}}
{{- range .Values.ingress.hosts }}{{- $o = append $o (printf "%s://%s" $scheme .) }}{{- end -}}
{{- join "," $o -}}
{{- end -}}
{{- end }}

{{- define "ep.dbHost" -}}
{{ include "ep.fullname" . }}-postgresql
{{- end }}

{{/* Environment shared by the backend Deployment and the migration Job. */}}
{{- define "ep.backendEnv" -}}
- name: POD_IP
  valueFrom:
    fieldRef:
      fieldPath: status.podIP
- name: DJANGO_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "ep.appSecret" . }}
      key: {{ .Values.secret.secretKeyKey }}
- name: DJANGO_DEBUG
  value: "false"
- name: DJANGO_ALLOWED_HOSTS
  value: {{ include "ep.allowedHosts" . | quote }}
{{- with (include "ep.csrfOrigins" .) }}
- name: DJANGO_CSRF_TRUSTED_ORIGINS
  value: {{ . | quote }}
{{- end }}
- name: DJANGO_COOKIE_SECURE
  value: {{ .Values.config.cookieSecure | quote }}
- name: WEB_CONCURRENCY
  value: {{ .Values.config.webConcurrency | quote }}
{{- if .Values.postgresql.enabled }}
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "ep.pgSecret" . }}
      key: {{ .Values.postgresql.auth.passwordKey }}
- name: DATABASE_URL
  value: "postgres://{{ .Values.postgresql.auth.username }}:$(POSTGRES_PASSWORD)@{{ include "ep.dbHost" . }}:5432/{{ .Values.postgresql.auth.database }}"
{{- else }}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "ep.dbSecret" . }}
      key: {{ .Values.database.urlKey }}
{{- end }}
{{- with .Values.config.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end }}
