// Two narrow PMUX outputs share one complete equality decoder.
module narrow_shared_4(
    input [2:0] sel,
    input [31:0] data,
    output reg [3:0] y,
    output reg [3:0] z
);
always @* begin
    y = 4'h0;
    z = 4'h0;
    case (sel)
        3'd0: begin y = data[0 +: 4];  z = data[4 +: 4]; end
        3'd1: begin y = data[4 +: 4];  z = data[0 +: 4]; end
        3'd2: begin y = data[8 +: 4];  z = data[12 +: 4]; end
        3'd3: begin y = data[12 +: 4]; z = data[8 +: 4]; end
        3'd4: begin y = data[16 +: 4]; z = data[20 +: 4]; end
        3'd5: begin y = data[20 +: 4]; z = data[16 +: 4]; end
        3'd6: begin y = data[24 +: 4]; z = data[28 +: 4]; end
        3'd7: begin y = data[28 +: 4]; z = data[24 +: 4]; end
    endcase
end
endmodule
