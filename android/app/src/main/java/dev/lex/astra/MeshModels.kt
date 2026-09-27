package dev.lex.astra

data class PairingInfo(
    val host: String,
    val port: Int,
    val fingerprint: String,
    val code: String,
    val nodeId: String = ""
)

data class DiscoveredNode(
    val name: String,
    val host: String,
    val port: Int,
    val fingerprint: String,
    val nodeId: String = "",
    val version: String = ""
)

data class ChatMessage(
    val fromAstra: Boolean,
    val text: String
)

data class MeshUiState(
    val connected: Boolean = false,
    val paired: Boolean = false,
    val connecting: Boolean = false,
    val nodeName: String = "",
    val status: String = "Desconectado",
    val host: String = "",
    val discovered: List<DiscoveredNode> = emptyList(),
    val messages: List<ChatMessage> = emptyList()
)
