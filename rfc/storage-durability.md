# RFC: Concurrent Storage and Retrieval for Blob Storage

## Background
Current system writes to a single node and retrieves from the first available node. We want to improve durability by writing to all nodes while maintaining fast response times.

## Goals
1. Write blobs to all available nodes concurrently
2. Return response as soon as first successful write occurs
3. Maintain accurate metadata of blob locations
4. Implement smart retrieval from available nodes

## Proposed Design

### Upload Flow
1. **Concurrent Upload**
   - Get list of all available nodes
   - Use asyncio.gather to write to all nodes simultaneously
   - Return success to user after first successful write
   - Continue remaining writes in background
   - Track success/failure status per node

2. **Two-Phase Metadata Management**
   - Phase 1 (Initial Success):
     * Create metadata entry after first successful upload
     * Mark upload as "in_progress"
     * Track successful and pending nodes
     * Return success to user
   - Phase 2 (Background Updates):
     * Update metadata as each node completes
     * Track timestamps per node
     * Remove nodes from pending list
     * Mark as "completed" when all nodes finish
     * Log failed uploads for monitoring

### Retrieval Flow
1. **Smart Node Selection**
   - Get list of nodes containing the blob from metadata
   - Filter for currently active nodes
   - Select best node based on:
     * Node health status
     * Last successful heartbeat
     * Recent success rate

2. **Failover Strategy**
   - If primary node fails, immediately try next available node
   - Consider implementing concurrent retrieval from multiple nodes (race condition)
   - Return first successful response

## Technical Considerations

### Concurrency
- Use asyncio.gather for parallel uploads
- Implement reasonable timeouts
- Handle partial upload successes
- Track background upload completions

### Error Handling
- Handle node failures during upload/download
- Track failed uploads per node
- Implement basic retry logic for retrievals
- Log all failures for monitoring

### Metadata Structure
```python
blob_metadata = {
    "blob_id": str,
    "successful_nodes": List[str],  # nodes with successful uploads
    "upload_timestamps": Dict[str, datetime],  # per node
    "size": int,
    "checksum": str,
    "content_type": str,
    "upload_status": str,  # "in_progress" or "completed"
    "pending_nodes": List[str],  # nodes still processing upload
    "failed_nodes": List[str]  # nodes that failed upload
}

node_health = {
    "node_id": str,
    "last_heartbeat": datetime,
    "status": str,  # "active" or "inactive"
    "success_rate": float  # recent success rate
}
```

### Note on Replication
Traditional replication is not needed in this design because:
1. We write to all available nodes concurrently
2. Maximum durability is achieved immediately
3. No need for background replication processes
4. Simpler metadata management (nodes either have or don't have the data)
5. Eliminates complexity of managing replication factors

This approach trades storage efficiency for:
- Immediate durability
- Simpler system design
- Faster retrieval (more nodes have the data)
- Elimination of background replication processes

## Questions to Resolve
1. How long should we wait for background uploads?
2. How to handle cleanup if first upload succeeds but others fail?
3. What metrics determine the "best" node for retrieval?
4. How to handle nodes that come back online?
5. How to handle metadata updates if Redis operations fail?

## Success Metrics
1. Upload success rate
2. Retrieval latency
3. Node distribution of blobs
4. Node health status
5. Metadata consistency rate