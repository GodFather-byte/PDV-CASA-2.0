# Cria a tarefa agendada que instala as atualizações do programa sem pedir administrador ao operador.
# O instalador roda isto como administrador, uma vez por instalação ou atualização (ver src/atualizacao/tarefa.py).
#
# - A tarefa roda como SISTEMA o "<Programa>.exe --aplicar-atualizacao", que confere a assinatura, a edição, a versão e
#   o SHA-256 do pedido antes de instalar. Não recebe argumentos de quem a inicia.
# - Qualquer usuário autenticado pode INICIAR a tarefa (ler e executar: GRGX), mas não alterar nem apagar.
# - Nunca derruba a instalação: se algo falhar aqui, o programa volta ao caminho antigo (pede administrador).
param(
    [Parameter(Mandatory = $true)][string]$Nome,
    [Parameter(Mandatory = $true)][string]$Exe,
    [string]$Registro = ""
)
$ErrorActionPreference = "Stop"
function Anotar([string]$texto) {
    if ($Registro) { try { Add-Content -Path $Registro -Value ("{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $texto) } catch { } }
}
try {
    $acao = New-ScheduledTaskAction -Execute $Exe -Argument "--aplicar-atualizacao"
    $quem = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $regras = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Nome -Action $acao -Principal $quem -Settings $regras -Force | Out-Null

    $agenda = New-Object -ComObject Schedule.Service
    $agenda.Connect()
    $tarefa = $agenda.GetFolder("\").GetTask($Nome)
    $acesso = $tarefa.GetSecurityDescriptor(4)          # 4 = só a DACL
    if ($acesso -notmatch [regex]::Escape("(A;;GRGX;;;AU)")) {
        $tarefa.SetSecurityDescriptor($acesso + "(A;;GRGX;;;AU)", 0)
    }
    Anotar "Tarefa '$Nome' pronta."
    exit 0
} catch {
    Anotar ("Tarefa '$Nome' não foi criada: " + $_.Exception.Message)
    exit 0
}
