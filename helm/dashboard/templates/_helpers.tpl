{{- define "dashboard.fullname" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "dashboard.labels" -}}
app.kubernetes.io/name: dashboard
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "dashboard.selectorLabels" -}}
app.kubernetes.io/name: dashboard
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
