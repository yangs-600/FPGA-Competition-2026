// Sparse PMUX fixture: four explicit codes share b; all other codes use a.
module sparse_default_completion(
    input [3:0] sel,
    input [7:0] a,
    input [7:0] b,
    output reg [7:0] y
);
always @* begin
    y = a;
    case (sel)
        4'd2: y = b;
        4'd0: y = b;
        4'd3: y = b;
        4'd1: y = b;
    endcase
end
endmodule
