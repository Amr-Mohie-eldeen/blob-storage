# RFC: Concurrent Storage and Retrieval for Blob Storage

## **1️⃣ Background**
The current system writes to a **single node** and retrieves from the **first available node**.  
To improve durability, we propose **writing to all nodes concurrently** while ensuring **fast response times and efficient retrieval.**  

## **2️⃣ Goals**
1. Write blobs to **all available nodes concurrently**.
2. **Return a response as soon as the first successful write** occurs.
3. Maintain **accurate metadata** of blob locations.
4. Implement **smart retrieval logic** for efficient access.
5. Ensure **resilience to node failures** and implement **auto-repair mechanisms**.

---

## **3️⃣ Proposed Design**

### **🔹 Upload Flow**
1. **Concurrent Upload**
   - Retrieve **list of all available nodes**.
   - Use **`asyncio.gather()`** to write to **all nodes in parallel**.
   - Return **success response after first successful write**.
   - Continue remaining writes in the **background**.
   - Track **success/failure status per node**.

2. **Two-Phase Metadata Management**
   - **Phase 1 (Initial Success)**
     * Create **metadata entry** after first successful upload.
     * Mark upload as **"in_progress"**.
     * Track **successful and pending nodes**.
     * **Return success to user immediately**.
   - **Phase 2 (Background Updates)**
     * Update metadata as **each node completes**.
     * Track **timestamps per node**.
     * Remove nodes from **pending list**.
     * Mark as **"completed"** when all nodes finish.
     * Log **failed uploads** for monitoring.
     * If a file is stored on **less than X% of nodes**, mark as **"degraded"** and attempt **auto-repair**.

---

### **🔹 Retrieval Flow**
1. **Smart Node Selection**
   - Get list of **nodes containing the blob** from metadata.
   - Filter for **currently active nodes**.
   - Select the **best node** based on:
     * **Node health status**.
     * **Last successful heartbeat**.
     * **Recent success rate**.
     * **Real-time response time (if available).**

2. **Failover Strategy**
   - If **primary node fails**, immediately try **next available node**.
   - Consider **concurrent retrieval** from multiple nodes (race condition).
   - Return **first successful response**.

---

### **🔹 Handling Partial Upload Failures**
- If some nodes **fail to store the blob**, mark the file as **"degraded"**.
- Attempt **delayed retries** for failed nodes.
- If the file exists on **less than X% of nodes**, **trigger auto-repair**.

---

### **🔹 Auto-Recovery for Offline Nodes**
- If a node **goes offline during upload**, it **requests missing blobs** upon coming back.
- Nodes **sync missing metadata first** before accepting retrieval requests.

---

## **4️⃣ Technical Considerations**

### **🔹 Concurrency**
- Use **`asyncio.gather()`** for parallel uploads.
- Implement **reasonable timeouts** for background uploads.
- Handle **partial upload successes** and retries.
- Track **background upload completions asynchronously**.

---

### **🔹 Error Handling**
- Handle **node failures during upload/download**.
- Track **failed uploads per node** and attempt **retries**.
- Implement **basic retry logic for retrievals**.
- Log **all failures** for monitoring.

---

### **🔹 Metadata Structure**
```python
blob_metadata = {
    "blob_id": str,
    "successful_nodes": List[str],  # nodes where upload succeeded
    "upload_timestamps": Dict[str, datetime],  # per node
    "size": int,
    "checksum": str,
    "content_type": str,
    "upload_status": str,  # "in_progress", "completed", "degraded"
    "pending_nodes": List[str],  # nodes still processing upload
    "failed_nodes": List[str],  # nodes that failed upload
    "retry_attempts": int,  # Number of retry attempts for failed nodes
    "last_failed_retry": Optional[datetime],  # Last retry timestamp
}

node_health = {
    "node_id": str,
    "last_heartbeat": datetime,
    "status": str,  # "active" or "inactive"
    "success_rate": float,  # recent success rate
    "response_time": float,  # last measured response time in ms
}
```
## **5️⃣ Comparison to Traditional Replication**

This approach **avoids traditional replication** because:
1. **We write to all nodes upfront** instead of replicating later.
2. **Maximum durability is achieved immediately**.
3. **No need for background replication processes**.
4. **Simplifies metadata management**—nodes either have or **don’t have the data**.
5. **Eliminates replication factor tracking**, as all nodes participate in writes.

**Tradeoffs:**
✅ **Faster durability**, since all nodes receive data upfront.  
✅ **Simpler design**—no need to track replication factors.  
❌ **Higher storage cost**, as every node stores the same data.  


---

## **6️⃣ Open Questions to Resolve**

1. **How long should we wait for background uploads to complete?**
   - Fixed timeout or adaptive based on file size?
2. **What happens if some nodes fail during upload?**
   - Retry indefinitely? Mark as degraded? Trigger auto-repair?
3. **How do we determine the "best" node for retrieval?**
   - Static weights vs. real-time node health monitoring?
4. **What happens when a node comes back online?**
   - Should it auto-sync missing blobs?
5. **How do we handle Redis failures?**
   - Should metadata be backed up in etcd? Checkpointed to disk?


---

## **7️⃣ Success Metrics**

To measure effectiveness, track:
1. **Upload success rate** (percentage of full uploads completed).
2. **Retrieval latency** (time taken to fetch a blob).
3. **Node distribution of blobs** (how evenly data is distributed).
4. **Node health status** (uptime and success rates).
5. **Metadata consistency rate** (how often Redis/metadata aligns with actual data).


---

## **8️⃣ Conclusion**

This RFC proposes **concurrent writes** to **all nodes**, **failover-aware retrieval**, and **simplified metadata management**. The goal is to **maximize durability and retrieval speed** while ensuring **robust failure handling and auto-repair mechanisms**.

Would love feedback on:
- Edge cases we might have missed.
- How we can optimize retrieval even further.
- Best way to balance **storage cost vs. durability.**


---

### **Next Steps**

- Implement **concurrent write flow with `asyncio.gather()`**.
- Modify **metadata tracking** to include failure states.
- Implement **auto-repair mechanism** for node failures.
- Test **retrieval failover scenarios** with active node monitoring.
