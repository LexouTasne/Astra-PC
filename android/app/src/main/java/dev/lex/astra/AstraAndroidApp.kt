package dev.lex.astra

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

private val AstraColors: ColorScheme = darkColorScheme(
    primary = Color(0xFF63D7FF),
    secondary = Color(0xFF8CFFCF),
    background = Color(0xFF071018),
    surface = Color(0xFF0D1822),
    surfaceVariant = Color(0xFF152431)
)

@Composable
fun AstraAndroidApp(
    repository: MeshRepository,
    onScanQr: () -> Unit,
    onVoice: () -> Unit,
    onCamera: () -> Unit,
    onStartSensors: () -> Unit,
    onStopSensors: () -> Unit,
    onSendClipboard: () -> Unit,
    onImportModel: () -> Unit,
    onImportTokenizer: () -> Unit,
    onRemoveLocalModel: () -> Unit
) {
    val state by repository.state.collectAsState()
    var host by remember { mutableStateOf("") }
    var port by remember { mutableStateOf("8767") }
    var fingerprint by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var prompt by remember { mutableStateOf("") }

    MaterialTheme(colorScheme = AstraColors) {
        Surface(modifier = Modifier.fillMaxSize()) {
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                item {
                    Text(
                        "ASTRA // MESH",
                        style = MaterialTheme.typography.headlineMedium,
                        fontWeight = FontWeight.Black,
                        color = MaterialTheme.colorScheme.primary
                    )
                    Text(
                        when {
                            state.connected -> "${state.nodeName.ifBlank { state.host }} • MESH ONLINE"
                            state.localAiReady -> "QWEN LOCAL • STANDALONE READY"
                            else -> state.status
                        },
                        color = if (state.connected || state.localAiReady)
                            MaterialTheme.colorScheme.secondary
                        else
                            MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }

                item {
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant
                        ),
                        shape = RoundedCornerShape(20.dp)
                    ) {
                        Column(
                            Modifier.padding(16.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            Text("Cérebro local", fontWeight = FontWeight.Bold)
                            Text(
                                state.localAiStatus,
                                style = MaterialTheme.typography.bodySmall
                            )
                            Text(
                                "Opcional: importe Qwen3 0.6B ONNX + tokenizer.json. " +
                                    "Quando a Mesh cair, Astra responde no próprio celular.",
                                style = MaterialTheme.typography.bodySmall
                            )
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                OutlinedButton(onClick = onImportModel) {
                                    Text("MODEL.ONNX")
                                }
                                OutlinedButton(onClick = onImportTokenizer) {
                                    Text("TOKENIZER")
                                }
                            }
                            if (state.localAiReady) {
                                OutlinedButton(
                                    onClick = onRemoveLocalModel,
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    Text("REMOVER MODELO LOCAL")
                                }
                            }
                        }
                    }
                }

                if (!state.paired) {
                    item {
                        Card(
                            colors = CardDefaults.cardColors(
                                containerColor = MaterialTheme.colorScheme.surfaceVariant
                            ),
                            shape = RoundedCornerShape(20.dp)
                        ) {
                            Column(
                                Modifier.padding(16.dp),
                                verticalArrangement = Arrangement.spacedBy(10.dp)
                            ) {
                                Text("Parear com um Astra", fontWeight = FontWeight.Bold)
                                Button(onClick = onScanQr, modifier = Modifier.fillMaxWidth()) {
                                    Text("ESCANEAR QR DO PC")
                                }

                                OutlinedTextField(
                                    value = host,
                                    onValueChange = { host = it },
                                    label = { Text("IP / host do PC") },
                                    modifier = Modifier.fillMaxWidth()
                                )
                                OutlinedTextField(
                                    value = port,
                                    onValueChange = { port = it },
                                    label = { Text("Porta") },
                                    modifier = Modifier.fillMaxWidth()
                                )
                                OutlinedTextField(
                                    value = fingerprint,
                                    onValueChange = { fingerprint = it },
                                    label = { Text("Fingerprint TLS") },
                                    modifier = Modifier.fillMaxWidth()
                                )
                                OutlinedTextField(
                                    value = code,
                                    onValueChange = { code = it.take(6) },
                                    label = { Text("Código de 6 dígitos") },
                                    modifier = Modifier.fillMaxWidth()
                                )

                                Button(
                                    onClick = {
                                        repository.pair(
                                            PairingInfo(
                                                host = host.trim(),
                                                port = port.toIntOrNull() ?: 8767,
                                                fingerprint = fingerprint.trim(),
                                                code = code.trim()
                                            )
                                        )
                                    },
                                    enabled = host.isNotBlank() &&
                                        fingerprint.length >= 32 &&
                                        code.length == 6,
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    Text("PAREAR")
                                }
                            }
                        }
                    }

                    if (state.discovered.isNotEmpty()) {
                        item {
                            Text("Nós Astra encontrados", fontWeight = FontWeight.Bold)
                        }
                        items(state.discovered) { node ->
                            OutlinedButton(
                                onClick = {
                                    host = node.host
                                    port = node.port.toString()
                                    fingerprint = node.fingerprint
                                },
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Column(Modifier.fillMaxWidth()) {
                                    Text(node.name, fontWeight = FontWeight.Bold)
                                    Text(
                                        "${node.host}:${node.port} • v${node.version}",
                                        style = MaterialTheme.typography.bodySmall
                                    )
                                }
                            }
                        }
                    }
                }

                item {
                    Card(shape = RoundedCornerShape(20.dp)) {
                        Column(
                            Modifier.padding(16.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            Text(
                                if (state.connected) "Astra distribuída"
                                else "Astra local",
                                fontWeight = FontWeight.Bold
                            )
                            OutlinedTextField(
                                value = prompt,
                                onValueChange = { prompt = it },
                                label = {
                                    Text(
                                        if (state.connected)
                                            "Perguntar ao cérebro Mesh"
                                        else
                                            "Perguntar ao Qwen local"
                                    )
                                },
                                modifier = Modifier.fillMaxWidth(),
                                minLines = 2
                            )
                            Button(
                                onClick = {
                                    repository.sendAsk(prompt)
                                    prompt = ""
                                },
                                enabled = prompt.isNotBlank() &&
                                    (state.connected || state.localAiReady),
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Text(
                                    if (state.connected)
                                        "ENVIAR PELA MESH"
                                    else
                                        "RODAR NO CELULAR"
                                )
                            }
                            OutlinedButton(
                                onClick = onVoice,
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Text("VOZ")
                            }
                        }
                    }
                }

                if (state.paired) {
                    item {
                        Card(shape = RoundedCornerShape(20.dp)) {
                            Column(
                                Modifier.padding(16.dp),
                                verticalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                Text("Dispositivo Mesh", fontWeight = FontWeight.Bold)
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Button(onClick = onCamera) { Text("CÂMERA") }
                                    Button(onClick = { repository.requestContext() }) { Text("PC") }
                                }
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    OutlinedButton(onClick = onStartSensors) {
                                        Text("SENSORES ON")
                                    }
                                    OutlinedButton(onClick = onStopSensors) {
                                        Text("SENSORES OFF")
                                    }
                                }
                                OutlinedButton(
                                    onClick = onSendClipboard,
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    Text("MANDAR CLIPBOARD PRO PC")
                                }
                            }
                        }
                    }
                }

                items(state.messages) { message ->
                    Box(
                        modifier = Modifier.fillMaxWidth(),
                        contentAlignment = if (message.fromAstra)
                            Alignment.CenterStart else Alignment.CenterEnd
                    ) {
                        Text(
                            message.text,
                            modifier = Modifier
                                .background(
                                    if (message.fromAstra)
                                        MaterialTheme.colorScheme.surfaceVariant
                                    else
                                        MaterialTheme.colorScheme.primary.copy(alpha = 0.18f),
                                    RoundedCornerShape(14.dp)
                                )
                                .padding(12.dp)
                        )
                    }
                }

                if (state.paired) {
                    item {
                        OutlinedButton(
                            onClick = { repository.disconnectAndForget() },
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text("REMOVER PAREAMENTO")
                        }
                    }
                }

                item { Spacer(Modifier.height(24.dp)) }
            }
        }
    }
}
