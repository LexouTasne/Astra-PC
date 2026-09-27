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
import androidx.compose.foundation.layout.weight
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
    onSendClipboard: () -> Unit
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
                modifier = Modifier
                    .fillMaxSize()
                    .padding(16.dp),
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
                        if (state.nodeName.isBlank()) state.status
                        else "${state.nodeName} • ${state.status}",
                        color = if (state.connected) MaterialTheme.colorScheme.secondary
                        else MaterialTheme.colorScheme.onSurfaceVariant
                    )
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
                                Text("Parear dispositivo", fontWeight = FontWeight.Bold)
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
                            Text("Astra Mesh encontrada na rede", fontWeight = FontWeight.Bold)
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
                } else {
                    item {
                        Row(
                            Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            Button(onClick = onVoice, modifier = Modifier.weight(1f)) {
                                Text("VOZ")
                            }
                            Button(onClick = onCamera, modifier = Modifier.weight(1f)) {
                                Text("CÂMERA")
                            }
                            Button(
                                onClick = { repository.requestContext() },
                                modifier = Modifier.weight(1f)
                            ) {
                                Text("PC")
                            }
                        }
                    }

                    item {
                        Row(
                            Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            OutlinedButton(
                                onClick = onStartSensors,
                                modifier = Modifier.weight(1f)
                            ) { Text("SENSORES ON") }
                            OutlinedButton(
                                onClick = onStopSensors,
                                modifier = Modifier.weight(1f)
                            ) { Text("SENSORES OFF") }
                            OutlinedButton(
                                onClick = onSendClipboard,
                                modifier = Modifier.weight(1f)
                            ) { Text("CLIPBOARD") }
                        }
                    }

                    item {
                        OutlinedTextField(
                            value = prompt,
                            onValueChange = { prompt = it },
                            label = { Text("Falar com Astra no PC") },
                            modifier = Modifier.fillMaxWidth(),
                            minLines = 2
                        )
                        Spacer(Modifier.height(8.dp))
                        Button(
                            onClick = {
                                repository.sendAsk(prompt)
                                prompt = ""
                            },
                            enabled = state.connected && prompt.isNotBlank(),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text("ENVIAR PARA ASTRA")
                        }
                    }

                    items(state.messages) { message ->
                        Box(
                            modifier = Modifier.fillMaxWidth(),
                            contentAlignment = if (message.fromAstra) Alignment.CenterStart
                            else Alignment.CenterEnd
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
