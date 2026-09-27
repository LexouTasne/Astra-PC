package dev.lex.astra

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo

class NsdDiscovery(
    context: Context,
    private val onNode: (DiscoveredNode) -> Unit
) {
    private val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private var discoveryListener: NsdManager.DiscoveryListener? = null

    fun start() {
        if (discoveryListener != null) return

        val listener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String?) = Unit
            override fun onDiscoveryStopped(serviceType: String?) = Unit
            override fun onStartDiscoveryFailed(serviceType: String?, errorCode: Int) {
                stop()
            }
            override fun onStopDiscoveryFailed(serviceType: String?, errorCode: Int) = Unit

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                if (!serviceInfo.serviceType.contains("_astra-mesh")) return
                @Suppress("DEPRECATION")
                nsd.resolveService(
                    serviceInfo,
                    object : NsdManager.ResolveListener {
                        override fun onResolveFailed(serviceInfo: NsdServiceInfo?, errorCode: Int) = Unit

                        override fun onServiceResolved(info: NsdServiceInfo) {
                            val attrs = info.attributes.mapValues {
                                it.value.toString(Charsets.UTF_8)
                            }
                            @Suppress("DEPRECATION")
                            val host = info.host?.hostAddress ?: return
                            val fingerprint = attrs["fingerprint"] ?: return
                            onNode(
                                DiscoveredNode(
                                    name = info.serviceName,
                                    host = host,
                                    port = info.port,
                                    fingerprint = fingerprint,
                                    nodeId = attrs["node_id"] ?: "",
                                    version = attrs["version"] ?: ""
                                )
                            )
                        }
                    }
                )
            }

            override fun onServiceLost(serviceInfo: NsdServiceInfo) = Unit
        }

        discoveryListener = listener
        nsd.discoverServices("_astra-mesh._tcp.", NsdManager.PROTOCOL_DNS_SD, listener)
    }

    fun stop() {
        discoveryListener?.let {
            try {
                nsd.stopServiceDiscovery(it)
            } catch (_: Exception) {
            }
        }
        discoveryListener = null
    }
}
