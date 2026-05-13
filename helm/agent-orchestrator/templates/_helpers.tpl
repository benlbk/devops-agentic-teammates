{{- define "agent-orchestrator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "agent-orchestrator.fullname" -}}
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

{{- define "agent-orchestrator.labels" -}}
helm.sh/chart: {{ include "agent-orchestrator.name" . }}-{{ .Chart.Version | replace "+" "_" }}
{{ include "agent-orchestrator.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "agent-orchestrator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agent-orchestrator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
